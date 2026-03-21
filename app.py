"""
NutriRun — Interface Gradio

Point d'entrée de l'application.
Lancement : python app.py
Interface : http://localhost:7860
"""

import gradio as gr
from dotenv import load_dotenv

load_dotenv()

from src.profile import init_profile
from src.agent import init_agent, run_agent
from src.strava import is_strava_configured


# Initialisation

print("🚀 Démarrage de NutriRun...")

try:
    profile = init_profile()
except (FileNotFoundError, ValueError) as e:
    print(f"❌ {e}")
    exit(1)

agent, _, _, _ = init_agent(profile, model_name="gpt-oss:120b-cloud")

strava_ok = is_strava_configured()
strava_status = "✅ Connecté" if strava_ok else "❌ Non configuré"
print(f"📡 Strava : {strava_status}")


# Fonctions de l'interface


def generate_plan(question: str, preferences: str, state: dict):
    """Génère un plan alimentaire à partir de la description de séance."""
    # Lance l'agent et formate les résultats pour chaque onglet Gradio
    if not question.strip():
        return (
            "Décris ta séance pour commencer.",
            "", "", "", "", state,
        )

    # Préférences
    prefs = preferences.strip() if preferences.strip() else None

    # Exécuter l'agent
    result = run_agent(agent, question, preferences=prefs)

    # Stocker pour la régénération
    state = {"result": result, "question": question}

    # Extraire les résultats
    params = result.get("session_params", {})
    macros = result.get("macros_finaux", {})
    calcul = result.get("calcul_result", {})

    # --- Résumé séance ---
    if result.get("parsing_error"):
        session_summary = f"⚠️ {result['parsing_error']}"
    elif params:
        session_summary = format_session_summary(params, result)
    else:
        session_summary = "Erreur lors du parsing de la séance."

    # --- Macros ---
    if macros:
        macros_text = format_macros(macros)
    else:
        macros_text = ""

    # --- Plan alimentaire ---
    plan = result.get("plan_alimentaire", "Erreur lors de la génération.")

    # --- Détails calcul ---
    calcul_text = calcul.get("resume", "") if calcul else ""

    # --- Strava ---
    strava_text = format_strava(result)

    return session_summary, macros_text, plan, calcul_text, strava_text, state


def regenerate_plan(question: str, preferences: str, feedback: str, state: dict):
    """Régénère le plan en tenant compte du feedback."""
    if not state.get("result"):
        return "Génère d'abord un plan avant de le modifier.", state

    q = state.get("question") or question
    prefs = preferences.strip() if preferences.strip() else None
    fb = feedback.strip() if feedback.strip() else None

    result = run_agent(agent, q, preferences=prefs, feedback=fb)
    state = {"result": result, "question": q}

    return result.get("plan_alimentaire", "Erreur lors de la régénération."), state


# Fonctions de formatage

TYPE_EMOJIS = {
    "footing": "🏃", "fractionne": "⚡", "seuil": "🎯",
    "sortie_longue": "🛤️", "trail": "⛰️", "repos": "😴", "competition": "🏆",
}


def format_session_summary(params: dict, result: dict) -> str:
    t = params.get("type_seance", "?")
    emoji = TYPE_EMOJIS.get(t, "🏃")

    lines = [f"### {emoji} {t.replace('_', ' ').upper()}"]

    duree = params.get("duree_min", 0)
    if duree:
        h, m = divmod(int(duree), 60)
        time_str = f"{h}h{m:02d}" if h else f"{m} min"
        lines.append(f"**Durée** : {time_str}")

    if params.get("distance_km"):
        lines.append(f"**Distance** : {params['distance_km']} km")

    if params.get("allure_min_km"):
        mins = int(params["allure_min_km"])
        secs = int((params["allure_min_km"] - mins) * 60)
        lines.append(f"**Allure** : {mins}:{secs:02d} /km")

    dp = params.get("denivele_positif_m", 0)
    dn = params.get("denivele_negatif_m", 0)
    if dp or dn:
        lines.append(f"**Dénivelé** : +{dp}m / -{dn}m")

    if params.get("heure_seance"):
        lines.append(f"**Horaire** : {params['heure_seance']}")

    # Dépense
    depense = result.get("depense_calibree_kcal")
    if depense:
        dep_line = f"**Dépense séance** : {depense} kcal"
        factor = result.get("strava_calibration_factor", 1.0)
        if factor != 1.0:
            dep_line += f" *(calibré Strava ×{factor})*"
        lines.append(dep_line)

    return "\n\n".join(lines)


def format_macros(macros: dict) -> str:
    total = macros.get("calories_cible_kcal", "?")
    lines = [
        f"### 🎯 Objectifs du jour : {total} kcal",
        "",
        f"| Macro | Grammes | g/kg |",
        f"|-------|---------|------|",
        f"| 🍞 Glucides | {macros.get('glucides_g', '?')}g | {macros.get('glucides_g_par_kg', '?')} |",
        f"| 🥩 Protéines | {macros.get('proteines_g', '?')}g | {macros.get('proteines_g_par_kg', '?')} |",
        f"| 🥑 Lipides | {macros.get('lipides_g', '?')}g | {macros.get('lipides_g_par_kg', '?')} |",
    ]
    return "\n".join(lines)


def format_strava(result: dict) -> str:
    sessions = result.get("strava_sessions")
    if not sessions:
        return "Strava non connecté ou aucune séance similaire trouvée."

    # Vérifier si au moins une séance a des calories
    has_calories = any(s.get("calories_montre") for s in sessions)

    lines = ["### 📊 Séances similaires dans ton historique", ""]

    if has_calories:
        lines.append("| Date | Distance | Durée | D+ | Calories | FC moy |")
        lines.append("|------|----------|-------|----|----------|--------|")
    else:
        lines.append("| Date | Distance | Durée | D+ | FC moy |")
        lines.append("|------|----------|-------|----|--------|")

    for s in sessions:
        fc = f"{s['fc_moyenne']:.0f}" if s.get("fc_moyenne") else "—"
        if has_calories:
            cal = f"{s['calories_montre']}" if s.get("calories_montre") else "—"
            lines.append(
                f"| {s['date']} | {s['distance_km']}km | "
                f"{s['duree_min']}min | +{s['denivele_m']}m | "
                f"{cal} | {fc} |"
            )
        else:
            lines.append(
                f"| {s['date']} | {s['distance_km']}km | "
                f"{s['duree_min']}min | +{s['denivele_m']}m | {fc} |"
            )

    factor = result.get("strava_calibration_factor", 1.0)
    if factor != 1.0:
        lines.append(f"\n*Facteur de calibration appliqué : ×{factor}*")
    else:
        lines.append(f"\n*Tes données correspondent bien aux estimations théoriques (calibration ×1.0)*")

    return "\n".join(lines)


# Interface Gradio

CUSTOM_CSS = """
/* ── Force light mode — empêche le mode sombre ── */
:root, :root .dark, .dark {
    --body-background-fill: #ffffff !important;
    --background-fill-primary: #ffffff !important;
    --background-fill-secondary: #ffffff !important;
    --block-background-fill: #ffffff !important;
    --panel-background-fill: #ffffff !important;
    --input-background-fill: #ffffff !important;
    --table-even-background-fill: #ffffff !important;
    --table-odd-background-fill: #fafafa !important;
    --body-text-color: #1a1a1a !important;
    --block-label-text-color: #444 !important;
    --block-title-text-color: #1a1a1a !important;
    --block-border-color: #e0dbd3 !important;
    --border-color-primary: #e0dbd3 !important;
    --neutral-100: #f5f5f5 !important;
    --neutral-200: #e8e5e0 !important;
    color-scheme: light !important;
}
body.dark, .dark .gradio-container {
    background: #ffffff !important;
    color: #1a1a1a !important;
}

/* ── Global ── */
.gradio-container {
    max-width: 960px !important;
    margin: 0 auto !important;
    background: #ffffff !important;
}

/* ── Forcer le blanc sur tous les blocs Gradio ── */
.gr-group, .gr-panel, .gr-box, .gr-form,
.gradio-group, .gradio-panel, .gradio-box,
.block, .form, .panel {
    background: #fff !important;
    background-color: #fff !important;
}

/* ── Hero header — dégradé plus prononcé avec lueur orange ── */
.nutri-hero {
    background: linear-gradient(135deg, #0d0d1a 0%, #1a1a3e 30%, #0f3460 60%, #1a4a6e 100%);
    border-radius: 16px;
    padding: 36px 40px 28px;
    margin-bottom: 8px;
    color: white;
    position: relative;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(15,52,96,0.3);
}
.nutri-hero::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 260px; height: 260px;
    background: radial-gradient(circle, rgba(255,140,50,0.25) 0%, rgba(255,100,30,0.08) 50%, transparent 70%);
    border-radius: 50%;
}
.nutri-hero::after {
    content: '';
    position: absolute;
    bottom: -40px; left: 20%;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(255,140,50,0.1) 0%, transparent 70%);
    border-radius: 50%;
}
.nutri-hero h1 {
    margin: 0 0 4px 0;
    font-size: 2.2rem;
    font-weight: 800;
    letter-spacing: -0.5px;
    color: #fff !important;
    position: relative;
}
.nutri-hero .nutri-accent {
    color: #ff8c32;
}
.nutri-hero .nutri-sub {
    font-size: 0.95rem;
    color: rgba(255,255,255,0.7);
    margin: 0;
    position: relative;
}
.nutri-hero .nutri-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
    position: relative;
}
.nutri-hero .nutri-badge {
    display: inline-block;
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.8rem;
    color: rgba(255,255,255,0.85);
    backdrop-filter: blur(4px);
}
.nutri-hero .nutri-badge-strava {
    background: rgba(252,82,0,0.2);
    border-color: rgba(252,82,0,0.35);
    color: #ff8c60;
}

/* ── Input card ── */
.input-card {
    background: #fff;
    border: 1px solid #e0dbd3;
    border-radius: 14px;
    padding: 24px 28px 20px;
    margin-bottom: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.input-card .gr-textbox textarea {
    border-radius: 10px !important;
}

/* ── Generate button ── */
#generate-btn {
    background: linear-gradient(135deg, #ff8c32 0%, #e06b10 100%) !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 1rem !important;
    letter-spacing: 0.5px !important;
    height: 100% !important;
    min-height: 72px !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
    box-shadow: 0 4px 14px rgba(255,140,50,0.25) !important;
}
#generate-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(255,140,50,0.35) !important;
}

/* ── Regen button ── */
#regen-btn {
    border-radius: 12px !important;
    font-weight: 600 !important;
    min-height: 72px !important;
    height: 100% !important;
    border: 2px solid #e0dbd3 !important;
    background: #fff !important;
    color: #444 !important;
    transition: border-color 0.15s ease !important;
}
#regen-btn:hover {
    border-color: #ff8c32 !important;
    color: #e06b10 !important;
}

/* ── Examples — cadre blanc uniforme ── */
.examples-row {
    background: #fff;
    border: 1px solid #e0dbd3;
    border-radius: 14px;
    padding: 16px 24px;
    margin-bottom: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.examples-row .gr-samples-table {
    border: none !important;
    background: transparent !important;
}
.examples-row button.gr-sample-btn, .examples-row .gr-samples-table td {
    border-radius: 20px !important;
    font-size: 0.82rem !important;
    padding: 6px 16px !important;
}

/* ── Tabs ── */
.result-tabs .tab-nav button {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    border-radius: 10px 10px 0 0 !important;
    padding: 10px 20px !important;
}
.result-tabs .tab-nav button.selected {
    background: #fff !important;
    color: #e06b10 !important;
    border-bottom: 3px solid #ff8c32 !important;
}
.result-tabs .tabitem {
    background: #fff;
    border: 1px solid #e0dbd3;
    border-top: none;
    border-radius: 0 0 14px 14px;
    padding: 24px 28px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

/* ── Result cards — cadre blanc uniforme (plus de fond gris) ── */
.result-card {
    background: #fff;
    border: 1px solid #e0dbd3;
    border-radius: 12px;
    padding: 20px 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
}

/* ── Feedback zone ── */
.feedback-zone {
    border-top: 1px solid #e0dbd3;
    margin-top: 20px;
    padding-top: 18px;
}

/* ── Footer ── */
.nutri-footer {
    text-align: center;
    padding: 20px 0 8px;
}
.nutri-footer p {
    font-size: 0.78rem;
    color: #aaa;
    margin: 0;
}

/* ── Markdown tables — style uniforme ── */
.result-card table, .tabitem table {
    border-collapse: separate;
    border-spacing: 0;
    width: 100%;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #e0dbd3;
    margin: 8px 0;
}
.result-card th, .tabitem th {
    background: #faf7f2;
    font-weight: 600;
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    padding: 10px 14px;
    color: #555;
}
.result-card td, .tabitem td {
    padding: 10px 14px;
    font-size: 0.88rem;
    border-top: 1px solid #eee;
    background: #fff;
}
.result-card tr:hover td, .tabitem tr:hover td {
    background: #fdf8f3;
}
"""

with gr.Blocks(
    title="NutriRun",
    theme=gr.themes.Soft(
        primary_hue="orange",
        secondary_hue="stone",
        neutral_hue="stone",
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
    ),
    css=CUSTOM_CSS,
    js="() => { document.body.classList.remove('dark'); document.documentElement.style.colorScheme = 'light'; }",
) as app:

    # --- Hero Header ---
    strava_badge_class = "nutri-badge nutri-badge-strava" if strava_ok else "nutri-badge"
    gr.HTML(f"""
    <div class="nutri-hero">
        <h1>Nutri<span class="nutri-accent">Run</span></h1>
        <p class="nutri-sub">Dis-lui ta séance, il compose ton assiette.</p>
        <div class="nutri-badges">
            <span class="nutri-badge">{profile['sexe'].upper()}</span>
            <span class="nutri-badge">{profile['age']} ans</span>
            <span class="nutri-badge">{profile['poids_kg']} kg &middot; {profile['taille_cm']} cm</span>
            <span class="nutri-badge">BMR {profile['metabolisme_base_kcal']} kcal</span>
            <span class="{strava_badge_class}">Strava {strava_status}</span>
        </div>
    </div>
    """)

    # --- Zone de saisie ---
    with gr.Group(elem_classes="input-card"):
        with gr.Row():
            with gr.Column(scale=3):
                input_text = gr.Textbox(
                    label="Décris ta séance du jour",
                    placeholder="Ex : Footing 45min à 5:00/km ce matin, Trail 2h 600D+, 10×400m récup 1'30...",
                    lines=2,
                    show_label=True,
                )
            with gr.Column(scale=2):
                preferences_text = gr.Textbox(
                    label="Préférences du jour (optionnel)",
                    placeholder="Ex : Plutôt sucré ce matin, j'ai des restes de riz, pas le temps de cuisiner...",
                    lines=2,
                )
            with gr.Column(scale=1, min_width=150):
                submit_btn = gr.Button(
                    "GÉNÉRER",
                    variant="primary",
                    size="lg",
                    elem_id="generate-btn",
                )

    with gr.Group(elem_classes="examples-row"):
        gr.Examples(
            examples=[
                ["Footing de 45 minutes à 5:00 min/km ce matin"],
                ["Trail 1h45, 15km avec 600m D+ dimanche matin"],
                ["Fractionné 10x400m récupération 1min30, ce soir à 18h"],
                ["Sortie longue 1h30 à 5:30/km samedi matin"],
                ["Séance seuil 3x10min à 4:15/km le midi"],
                ["Jour de repos"],
            ],
            inputs=input_text,
            label="Exemples de séances",
        )

    # --- Resultats ---
    with gr.Tabs(elem_classes="result-tabs"):

        # Tab 1 : Plan alimentaire
        with gr.Tab("🍽️ Plan alimentaire", id="tab-plan"):
            plan_output = gr.Markdown(
                "*Ton plan alimentaire apparaîtra ici après génération.*",
            )
            with gr.Group(elem_classes="feedback-zone"):
                with gr.Row():
                    with gr.Column(scale=4):
                        feedback_text = gr.Textbox(
                            label="Ajuster le plan",
                            placeholder="Ex : Remplace le saumon, je suis végétarien, plus de glucides au petit-déj...",
                            lines=2,
                        )
                    with gr.Column(scale=1, min_width=150):
                        regen_btn = gr.Button(
                            "RÉGÉNÉRER",
                            variant="secondary",
                            size="lg",
                            elem_id="regen-btn",
                        )

        # Tab 2 : Seance & Macros
        with gr.Tab("📊 Séance & Macros", id="tab-macros"):
            with gr.Row(equal_height=True):
                with gr.Column():
                    with gr.Group(elem_classes="result-card"):
                        gr.HTML('<p style="margin:0 0 8px;font-weight:700;font-size:0.85rem;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Séance détectée</p>')
                        session_output = gr.Markdown("*Les détails de ta séance apparaîtront ici.*")
                with gr.Column():
                    with gr.Group(elem_classes="result-card"):
                        gr.HTML('<p style="margin:0 0 8px;font-weight:700;font-size:0.85rem;color:#888;text-transform:uppercase;letter-spacing:0.5px;">Objectifs Macros</p>')
                        macros_output = gr.Markdown("*Les objectifs macros apparaîtront ici.*")
            calcul_output = gr.Markdown("")

        # Tab 3 : Strava
        with gr.Tab("📡 Strava", id="tab-strava"):
            with gr.Group(elem_classes="result-card"):
                strava_output = gr.Markdown(
                    "Strava non connecté." if not strava_ok
                    else "*Les données Strava apparaîtront ici après génération.*"
                )

    # --- Footer ---
    gr.HTML("""
    <div class="nutri-footer">
        <p>NutriRun &mdash; Projet IA Générative &middot; Université Paris Dauphine &mdash; RAG + Agent LangGraph + Strava API</p>
    </div>
    """)

    # --- État par session (remplace la variable globale) ---
    session_state = gr.State({"result": None, "question": None})

    # --- Événements ---
    all_outputs = [
        session_output,
        macros_output,
        plan_output,
        calcul_output,
        strava_output,
        session_state,
    ]

    submit_btn.click(
        fn=generate_plan,
        inputs=[input_text, preferences_text, session_state],
        outputs=all_outputs,
    )

    input_text.submit(
        fn=generate_plan,
        inputs=[input_text, preferences_text, session_state],
        outputs=all_outputs,
    )

    regen_btn.click(
        fn=regenerate_plan,
        inputs=[input_text, preferences_text, feedback_text, session_state],
        outputs=[plan_output, session_state],
    )


# Lancement

if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )