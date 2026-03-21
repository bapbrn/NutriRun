"""
NutriRun — Agent LangGraph

Agent nutritionnel avec routage intelligent par le LLM.

Architecture :
1. Parsing       — Le LLM extrait les paramètres de la séance
2. Preferences   — L'utilisateur précise ses envies du jour 
3. Validation    — Vérification déterministe des paramètres
4. Repair        — Correction automatique si validation échoue
5. Router        — Le LLM décide quels outils appeler
6. Tool nodes    — Exécution des outils sélectionnés par le routeur
7. Merge         — Fusion des résultats et calibration
8. Generation    — Le LLM génère le plan alimentaire
9. Output        — Mise en forme finale

Le routeur est le cœur de l'agent : il analyse la séance, détecte le mode
(entraînement / pré-course / jour de course / repos) et choisit dynamiquement
quels outils sont nécessaires.
"""

import json
from typing import TypedDict, Optional, List
from pydantic import BaseModel, Field

from langchain_ollama import OllamaLLM
from langchain_core.output_parsers import PydanticOutputParser
from langgraph.graph import StateGraph, END

from src.rag import init_rag, format_docs
from src.calculator import calculer_journee
from src.strava import (
    is_strava_configured,
    get_recent_activities,
    find_similar_sessions,
    compute_calibration_factor,
)
from src.prompts import (
    build_parsing_prompt,
    build_repair_prompt,
    build_generation_prompt,
    build_prerace_prompt,
    build_raceday_prompt,
    ROUTER_PROMPT,
)



# Modèles de données


class TrainingSession(BaseModel):
    """Paramètres extraits de la description d'entraînement."""
    type_seance: str = Field(
        description="Type parmi: footing, fractionne, seuil, sortie_longue, trail, repos, competition, pre_course, jour_course"
    )
    duree_min: int = Field(description="Durée totale en minutes")
    allure_min_km: Optional[float] = Field(default=None, description="Allure en décimal (5:30 → 5.5). null si non spécifié.")
    distance_km: Optional[float] = Field(default=None, description="Distance en km. null si non spécifié.")
    denivele_positif_m: int = Field(default=0, description="Dénivelé positif en mètres. 0 si plat.")
    denivele_negatif_m: int = Field(default=0, description="Dénivelé négatif en mètres. 0 si plat.")
    heure_seance: Optional[str] = Field(default=None, description="Moment : matin, midi, apres-midi, soir")
    course_nom: Optional[str] = Field(default=None, description="Nom de la course mentionnée (ex: 'marathon', '10km', 'trail des monts'). null si pas de course mentionnée.")
    course_distance_km: Optional[float] = Field(default=None, description="Distance de la course mentionnée en km. null si non précisée.")
    course_dans_jours: Optional[int] = Field(default=None, description="Nombre de jours avant la course (ex: 'dans 5 jours' → 5, 'demain' → 1, 'aujourd'hui' → 0). null si non précisé.")


class RouterDecision(BaseModel):
    """Décision du routeur : quels outils appeler."""
    mode: str = Field(description="Mode : entrainement, pre_course, jour_course, repos")
    reasoning: str = Field(description="Explication courte de la décision")
    use_strava: bool = Field(description="Chercher des séances similaires sur Strava ?")
    use_rag_timing: bool = Field(description="Chercher des infos sur le timing nutritionnel ?")
    use_rag_recettes: bool = Field(description="Chercher des recettes adaptées ?")
    use_rag_nutrition: bool = Field(description="Chercher des recommandations nutritionnelles ?")
    use_rag_precompetition: bool = Field(default=False, description="Chercher le protocole pré-compétition ?")
    use_rag_jour_course: bool = Field(default=False, description="Chercher la stratégie jour de course ?")



# État de l'agent


class AgentState(TypedDict):
    question: str
    session_params: Optional[dict]
    parsing_error: Optional[str]
    preferences: Optional[str]
    validation_errors: Optional[List[str]]
    repair_attempts: int
    router_decision: Optional[dict]
    calcul_result: Optional[dict]
    strava_sessions: Optional[List[dict]]
    strava_calibration_factor: Optional[float]
    rag_timing_context: Optional[str]
    rag_recettes_context: Optional[str]
    rag_nutrition_context: Optional[str]
    rag_precompetition_context: Optional[str]
    rag_jour_course_context: Optional[str]
    depense_calibree_kcal: Optional[float]
    macros_finaux: Optional[dict]
    contexte_complet: Optional[str]
    plan_alimentaire: Optional[str]
    feedback: Optional[str]



# Nœuds du graphe


def create_agent_nodes(model: OllamaLLM, retriever, profile: dict):
    session_parser = PydanticOutputParser(pydantic_object=TrainingSession)
    session_format = session_parser.get_format_instructions()
    router_parser = PydanticOutputParser(pydantic_object=RouterDecision)
    router_format = router_parser.get_format_instructions()

    # --- PARSING ---
    def parsing_node(state: AgentState) -> dict:
        prompt = build_parsing_prompt(state["question"], session_format)
        response = model.invoke(prompt)
        try:
            session = session_parser.parse(response)
            return {"session_params": session.model_dump(), "parsing_error": None}
        except Exception:
            try:
                start = response.find("{")
                end = response.rfind("}") + 1
                if start != -1 and end > start:
                    raw = json.loads(response[start:end])
                    session = TrainingSession(**raw)
                    return {"session_params": session.model_dump(), "parsing_error": None}
            except Exception:
                pass
        return {"session_params": None, "parsing_error": "Impossible d'extraire les paramètres. Reformule ta séance."}

    # --- PREFERENCES ---
    def preferences_node(state: AgentState) -> dict:
        if state.get("preferences"):
            return {}
        return {"preferences": "Aucune préférence particulière"}

    # --- VALIDATION ---
    def validation_node(state: AgentState) -> dict:
        params = state.get("session_params")
        errors = []
        if params is None:
            return {"validation_errors": ["Pas de paramètres à valider."]}

        valid_types = ["footing", "fractionne", "seuil", "sortie_longue", "trail", "repos", "competition", "pre_course", "jour_course"]
        if params.get("type_seance") not in valid_types:
            errors.append(f"Type '{params.get('type_seance')}' invalide. Valides : {valid_types}")

        duree = params.get("duree_min", 0)
        if params.get("type_seance") not in ("repos", "pre_course"):
            if duree <= 0:
                errors.append(f"Durée invalide ({duree} min).")
            elif duree > 720:
                errors.append(f"Durée trop longue ({duree} min).")

        allure = params.get("allure_min_km")
        if allure is not None and (allure < 2.5 or allure > 12.0):
            errors.append(f"Allure invalide ({allure} min/km).")

        distance = params.get("distance_km")
        if distance is not None and (distance <= 0 or distance > 250):
            errors.append(f"Distance invalide ({distance} km).")

        dp = params.get("denivele_positif_m", 0) or 0
        dn = params.get("denivele_negatif_m", 0) or 0
        if dp < 0 or dp > 10000:
            errors.append(f"D+ invalide ({dp} m).")
        if dn < 0 or dn > 10000:
            errors.append(f"D- invalide ({dn} m).")

        return {"validation_errors": errors if errors else None, "repair_attempts": state.get("repair_attempts", 0)}

    # --- REPAIR ---
    def repair_node(state: AgentState) -> dict:
        attempts = state.get("repair_attempts", 0) + 1
        if attempts > 2:
            params = state.get("session_params", {})
            valid_types = ["footing", "fractionne", "seuil", "sortie_longue", "trail", "repos", "competition", "pre_course", "jour_course"]
            if params.get("type_seance") not in valid_types:
                params["type_seance"] = "footing"
            if not params.get("duree_min") or params["duree_min"] <= 0:
                params["duree_min"] = 45
            return {"session_params": params, "validation_errors": None, "repair_attempts": attempts}

        prompt = build_repair_prompt(
            session_params=json.dumps(state.get("session_params", {}), ensure_ascii=False, indent=2),
            validation_errors=str(state.get("validation_errors", [])),
            question=state["question"],
            format_instructions=session_format,
        )
        response = model.invoke(prompt)
        try:
            session = session_parser.parse(response)
            return {"session_params": session.model_dump(), "validation_errors": None, "repair_attempts": attempts}
        except Exception:
            try:
                start = response.find("{")
                end = response.rfind("}") + 1
                if start != -1 and end > start:
                    raw = json.loads(response[start:end])
                    session = TrainingSession(**raw)
                    return {"session_params": session.model_dump(), "validation_errors": None, "repair_attempts": attempts}
            except Exception:
                pass
        return {"repair_attempts": attempts}

    # --- ROUTER  ---
    def router_node(state: AgentState) -> dict:
        """Le LLM analyse la séance et décide quels outils appeler."""
        params = state["session_params"]
        strava_available = is_strava_configured()

        prompt = ROUTER_PROMPT.format(
            question=state["question"],
            type_seance=params.get("type_seance", ""),
            duree_min=params.get("duree_min", 0),
            distance_km=params.get("distance_km", "non spécifié"),
            denivele_positif_m=params.get("denivele_positif_m", 0),
            heure_seance=params.get("heure_seance", "non précisé"),
            strava_available="oui" if strava_available else "non",
            preferences=state.get("preferences", "aucune"),
            format_instructions=router_format,
        )
        response = model.invoke(prompt)

        try:
            decision = router_parser.parse(response)
            print(f"  Routeur : mode={decision.mode}, outils={[k for k, v in decision.model_dump().items() if k.startswith('use_') and v]}")
            print(f"  Raisonnement : {decision.reasoning}")
            return {"router_decision": decision.model_dump()}
        except Exception:
            try:
                start = response.find("{")
                end = response.rfind("}") + 1
                if start != -1 and end > start:
                    raw = json.loads(response[start:end])
                    decision = RouterDecision(**raw)
                    return {"router_decision": decision.model_dump()}
            except Exception:
                pass

            # Fallback : tout activer
            print("  Routeur : fallback, tous les outils activés")
            return {"router_decision": {
                "mode": "entrainement", "reasoning": "Fallback",
                "use_strava": strava_available, "use_rag_timing": True,
                "use_rag_recettes": True, "use_rag_nutrition": True,
                "use_rag_precompetition": False, "use_rag_jour_course": False,
            }}

    # --- CALCUL (toujours exécuté) ---
    def calcul_node(state: AgentState) -> dict:
        result = calculer_journee(profile, state["session_params"])
        return {"calcul_result": result}

    # --- STRAVA (conditionnel) ---
    def strava_node(state: AgentState) -> dict:
        decision = state.get("router_decision", {})
        if not decision.get("use_strava") or not is_strava_configured():
            return {"strava_sessions": None, "strava_calibration_factor": 1.0}
        try:
            activities = get_recent_activities(n=50)
            if not activities:
                return {"strava_sessions": None, "strava_calibration_factor": 1.0}
            params = state["session_params"]
            similar = find_similar_sessions(activities=activities, duree_min=params.get("duree_min", 0), denivele_m=params.get("denivele_positif_m", 0) or 0, max_results=5)
            if not similar:
                return {"strava_sessions": None, "strava_calibration_factor": 1.0}
            calibration = compute_calibration_factor(similar_sessions=similar, poids_kg=profile["poids_kg"], age=profile.get("age", 25), sexe=profile.get("sexe", "homme"))
            print(f"  Strava : {len(similar)} séances similaires, calibration ×{calibration}")
            return {"strava_sessions": similar, "strava_calibration_factor": calibration}
        except Exception as e:
            print(f"  Strava : erreur — {e}")
            return {"strava_sessions": None, "strava_calibration_factor": 1.0}

    # --- RAG TIMING (conditionnel) ---
    def rag_timing_node(state: AgentState) -> dict:
        if not state.get("router_decision", {}).get("use_rag_timing"):
            return {"rag_timing_context": None}
        params = state["session_params"]
        query = f"timing nutritionnel quand manger avant pendant après {params['type_seance']} {params.get('duree_min', 0)} minutes {params.get('heure_seance', '')}"
        docs = retriever.invoke(query)
        docs2 = retriever.invoke("collation récupération post-effort")
        all_docs = _deduplicate(docs, docs2)
        return {"rag_timing_context": format_docs(all_docs[:6])}

    # --- RAG RECETTES (conditionnel) ---
    def rag_recettes_node(state: AgentState) -> dict:
        if not state.get("router_decision", {}).get("use_rag_recettes"):
            return {"rag_recettes_context": None}
        type_s = state["session_params"]["type_seance"]
        queries = {"fractionne": "recettes protéines récupération", "seuil": "recettes protéines récupération", "sortie_longue": "recettes glucidiques énergie", "trail": "recettes glucidiques énergie", "repos": "recettes anti-inflammatoire récupération"}
        query = queries.get(type_s, "recettes sportives repas équilibré")
        docs = retriever.invoke(query)
        docs2 = retriever.invoke("collation snack smoothie")
        all_docs = _deduplicate(docs, docs2)
        return {"rag_recettes_context": format_docs(all_docs[:6])}

    # --- RAG NUTRITION (conditionnel) ---
    def rag_nutrition_node(state: AgentState) -> dict:
        if not state.get("router_decision", {}).get("use_rag_nutrition"):
            return {"rag_nutrition_context": None}
        params = state["session_params"]
        type_s = params["type_seance"]
        dp = params.get("denivele_positif_m", 0) or 0
        queries = {"trail": f"besoins nutritionnels trail dénivelé {dp}m", "fractionne": "besoins nutritionnels fractionné VMA", "sortie_longue": f"besoins nutritionnels sortie longue", "seuil": "besoins nutritionnels seuil tempo", "repos": "besoins nutritionnels jour repos"}
        query = queries.get(type_s, "besoins nutritionnels footing endurance")
        if dp > 0:
            query = queries.get("trail", query)
        docs = retriever.invoke(query)
        docs2 = retriever.invoke(f"plan alimentaire type jour {type_s}")
        all_docs = _deduplicate(docs, docs2)
        return {"rag_nutrition_context": format_docs(all_docs[:6])}

    # --- RAG PRÉ-COMPÉTITION (conditionnel) ---
    def rag_precompetition_node(state: AgentState) -> dict:
        if not state.get("router_decision", {}).get("use_rag_precompetition"):
            return {"rag_precompetition_context": None}
        docs = retriever.invoke("protocole semaine avant course charge glucidique")
        docs2 = retriever.invoke("veille de course alimentation fibres")
        all_docs = _deduplicate(docs, docs2)
        return {"rag_precompetition_context": format_docs(all_docs[:6])}

    # --- RAG JOUR DE COURSE ---
    def rag_jour_course_node(state: AgentState) -> dict:
        if not state.get("router_decision", {}).get("use_rag_jour_course"):
            return {"rag_jour_course_context": None}
        docs = retriever.invoke("petit déjeuner avant course ravitaillement pendant effort")
        docs2 = retriever.invoke("récupération post-course réhydratation")
        all_docs = _deduplicate(docs, docs2)
        return {"rag_jour_course_context": format_docs(all_docs[:6])}

    # --- MERGE ---
    def merge_node(state: AgentState) -> dict:
        calcul = state.get("calcul_result", {})
        depense_seance = calcul.get("depense_seance", {})
        depense_theorique = depense_seance.get("depense_seance_kcal", 0)
        calibration = state.get("strava_calibration_factor", 1.0) or 1.0
        depense_calibree = round(depense_theorique * calibration)

        # Si Strava a modifié la dépense, on recalcule les macros avec la nouvelle dépense
        if calibration != 1.0:
            from src.calculator import calculer_macros, calculer_depense_totale
            depense_totale = calculer_depense_totale(profile["depense_hors_entrainement_kcal"], depense_calibree)
            params = state["session_params"]
            macros = calculer_macros(
                poids_kg=profile["poids_kg"],
                type_seance=params.get("type_seance", "footing"),
                depense_totale_kcal=depense_totale,
                denivele_positif_m=params.get("denivele_positif_m", 0) or 0,
                duree_min=params.get("duree_min", 0),
                objectif_nutritionnel=profile.get("objectif_nutritionnel", "maintien"),
            )
        else:
            macros = calcul.get("macros", {}).copy()

        contexte_parts = []
        for key, label in [("rag_timing_context", "Timing"), ("rag_recettes_context", "Recettes"), ("rag_nutrition_context", "Nutrition"), ("rag_precompetition_context", "Pré-compétition"), ("rag_jour_course_context", "Jour de course")]:
            ctx = state.get(key)
            if ctx:
                contexte_parts.append(f"## {label}\n{ctx}")

        return {"depense_calibree_kcal": depense_calibree, "macros_finaux": macros, "contexte_complet": "\n\n".join(contexte_parts)}

    # --- GENERATION (choisit le bon prompt selon le mode) ---
    def generation_node(state: AgentState) -> dict:
        decision = state.get("router_decision", {})
        mode = decision.get("mode", "entrainement")
        params = state["session_params"]

        # Contexte Strava (commun à tous les modes)
        strava_info = ""
        if state.get("strava_sessions"):
            strava_info = "Séances similaires Strava :\n"
            for s in state["strava_sessions"]:
                strava_info += f"- {s['date']} : {s['distance_km']}km, {s['duree_min']}min\n"
            strava_info += f"Calibration : ×{state.get('strava_calibration_factor', 1.0)}"

        # Infos course : priorité au message de l'utilisateur, fallback sur le profil
        course_profile = dict(profile)
        if params.get("course_nom"):
            course_profile["objectif_course"] = params["course_nom"]
            # Si l'utilisateur mentionne une course différente, remettre le dénivelé à 0
            # sauf s'il a explicitement précisé un D+
            if params.get("denivele_positif_m", 0) == 0:
                course_profile["objectif_denivele_m"] = 0
        if params.get("course_distance_km"):
            course_profile["objectif_distance_km"] = params["course_distance_km"]

        # Calcul jours avant course
        jours_avant = "?"
        if params.get("course_dans_jours") is not None:
            jours_avant = str(-params["course_dans_jours"])

        # --- Mode pré-course → build_prerace_prompt ---
        if mode == "pre_course":
            prompt = build_prerace_prompt(
                profile=course_profile,
                macros=state["macros_finaux"],
                contexte_rag=state.get("contexte_complet", ""),
                strava_info=strava_info,
                preferences=state.get("preferences", "Aucune préférence"),
                feedback=state.get("feedback", ""),
                jours_avant_course=jours_avant,
            )

        # --- Mode jour de course → build_raceday_prompt ---
        elif mode == "jour_course":
            prompt = build_raceday_prompt(
                profile=course_profile,
                session_params=params,
                macros=state["macros_finaux"],
                depense_course=str(state.get("depense_calibree_kcal", "?")),
                contexte_rag=state.get("contexte_complet", ""),
                strava_info=strava_info,
                preferences=state.get("preferences", "Aucune préférence"),
                feedback=state.get("feedback", ""),
            )

        # --- Mode entraînement / repos → build_generation_prompt ---
        else:
            prompt = build_generation_prompt(
                profile=profile,
                session_params=params,
                macros=state["macros_finaux"],
                contexte_rag=state.get("contexte_complet", ""),
                strava_info=strava_info,
                preferences=state.get("preferences", "Aucune préférence"),
                feedback=state.get("feedback", ""),
            )

        response = model.invoke(prompt)
        return {"plan_alimentaire": response}

    return {
        "parsing": parsing_node, "preferences": preferences_node,
        "validation": validation_node, "repair": repair_node,
        "router": router_node, "calcul": calcul_node, "strava": strava_node,
        "rag_timing": rag_timing_node, "rag_recettes": rag_recettes_node,
        "rag_nutrition": rag_nutrition_node, "rag_precompetition": rag_precompetition_node,
        "rag_jour_course": rag_jour_course_node,
        "merge": merge_node, "generation": generation_node,
    }


def _deduplicate(docs1: list, docs2: list) -> list:
    """Déduplique deux listes de docs (basé sur les 80 premiers caractères)."""
    all_docs = list(docs1)
    seen = {hash(d.page_content[:80]) for d in docs1}
    for d in docs2:
        h = hash(d.page_content[:80])
        if h not in seen:
            all_docs.append(d)
            seen.add(h)
    return all_docs


# Graphe

def build_graph(nodes: dict) -> StateGraph:
    graph = StateGraph(AgentState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.set_entry_point("parsing")

    def parsing_router(state: AgentState) -> str:
        return END if state.get("parsing_error") else "preferences"
    graph.add_conditional_edges("parsing", parsing_router, {"preferences": "preferences", END: END})

    graph.add_edge("preferences", "validation")

    def validation_router(state: AgentState) -> str:
        return "repair" if state.get("validation_errors") else "router"
    graph.add_conditional_edges("validation", validation_router, {"repair": "repair", "router": "router"})

    graph.add_edge("repair", "validation")

    # Fan-out : après le routeur, tous les outils tournent en parallèle
    parallel_nodes = ["calcul", "strava", "rag_timing", "rag_recettes", "rag_nutrition", "rag_precompetition", "rag_jour_course"]
    for node in parallel_nodes:
        graph.add_edge("router", node)

    # Fan-in : tous les outils convergent vers merge
    for node in parallel_nodes:
        graph.add_edge(node, "merge")

    graph.add_edge("merge", "generation")
    graph.add_edge("generation", END)

    return graph


def init_agent(profile: dict, model_name: str = "gemma3:4b", knowledge_dir: str = "knowledge_base"):
    print("=" * 50)
    print("🏃 NutriRun — Initialisation de l'agent")
    print("=" * 50)
    model = OllamaLLM(model=model_name)
    print(f"  Modèle : {model_name}")
    vectordb, retriever, chunks = init_rag(knowledge_dir=knowledge_dir)
    nodes = create_agent_nodes(model, retriever, profile)
    graph = build_graph(nodes)
    agent = graph.compile()
    print(f"  Agent compilé — {len(nodes)} nœuds (dont routeur LLM)")
    print("=" * 50)
    return agent, model, vectordb, retriever


def run_agent(agent, question: str, preferences: str = None, feedback: str = None) -> dict:
    initial_state: AgentState = {
        "question": question, "session_params": None, "parsing_error": None,
        "preferences": preferences, "validation_errors": None, "repair_attempts": 0,
        "router_decision": None, "calcul_result": None,
        "strava_sessions": None, "strava_calibration_factor": None,
        "rag_timing_context": None, "rag_recettes_context": None, "rag_nutrition_context": None,
        "rag_precompetition_context": None, "rag_jour_course_context": None,
        "depense_calibree_kcal": None, "macros_finaux": None, "contexte_complet": None,
        "plan_alimentaire": None, "feedback": feedback,
    }
    return agent.invoke(initial_state)