"""
NutriRun — Module Calculs Déterministes

Calcule la dépense calorique d'une séance et les besoins en macronutriments selon le type de séance et le profil utilisateur.

Entièrement déterministes : tout est basé sur des formules et des tables. 

C'est le premier outil de NutriRun 
"""



# 1. ESTIMATION DE LA DISTANCE PARCOURUE


# Allures par défaut (min/km) si l'utilisateur ne précise ni distance ni allure
ALLURES_DEFAUT = {
    "footing": 5.5,
    "fractionne": 5.0,
    "seuil": 4.5,
    "sortie_longue": 5.5,
    "trail": 7.0,
    "competition": 4.5,
    "jour_course": 4.5,
    "repos": 0,
}


def estimer_distance(duree_min: int, allure_min_km: float = None, type_seance: str = "footing") -> float:
    """Estime la distance à partir de la durée et de l'allure (ou allure par défaut si non fournie)."""
    if allure_min_km is None:
        allure_min_km = ALLURES_DEFAUT.get(type_seance, 5.5)

    if allure_min_km <= 0:
        return 0

    return round(duree_min / allure_min_km, 1)




# 2. DÉPENSE CALORIQUE DE LA SÉANCE


# Coefficients d'intensité appliqués à la formule de base (1 kcal/kg/km)
COEFFICIENTS_INTENSITE = {
    "footing": 0.95,
    "fractionne": 1.15,
    "seuil": 1.1,
    "sortie_longue": 1.0,
    "trail": 1.0,
    "competition": 1.15,
    "jour_course": 1.15,
    "repos": 0,
}


def calculer_depense_seance(
    poids_kg: float,
    distance_km: float,
    type_seance: str = "footing",
    denivele_positif_m: int = 0,
    denivele_negatif_m: int = 0,
) -> dict:
    """
    Dépense calorique d'une séance.

    Route : poids × distance × coefficient d'intensité
    Trail : on ajoute le coût du dénivelé (coefficients de Minetti : D+ × 0.005, D- × 0.002)
    """
    if type_seance == "repos":
        return {
            "depense_seance_kcal": 0,
            "distance_km": 0,
            "coefficient": 0,
            "formule": "repos",
        }

    coeff = COEFFICIENTS_INTENSITE.get(type_seance, 1.0)

    # Trail : formule avec dénivelé
    if denivele_positif_m > 0 or denivele_negatif_m > 0:
        depense = poids_kg * (
            distance_km * coeff
            + denivele_positif_m * 0.005
            + denivele_negatif_m * 0.002
        )
        formule = "trail"
    else:
        depense = poids_kg * distance_km * coeff
        formule = "route"

    return {
        "depense_seance_kcal": round(depense),
        "distance_km": distance_km,
        "coefficient": coeff,
        "formule": formule,
    }




# 3. DÉPENSE CALORIQUE TOTALE DE LA JOURNÉE


def calculer_depense_totale(depense_hors_entrainement_kcal: float, depense_seance_kcal: float) -> int:
    """Dépense hors entraînement + dépense séance = dépense totale du jour."""
    return round(depense_hors_entrainement_kcal + depense_seance_kcal)



# 4. BESOINS EN MACRONUTRIMENTS


# Tables de besoins en g/kg/jour selon le type de séance

GLUCIDES_G_PAR_KG = {
    "repos": (3.0, 4.0),
    "footing": (5.0, 6.0),
    "seuil": (7.0, 8.0),
    "fractionne": (7.0, 9.0),
    "sortie_longue": (8.0, 10.0),
    "trail": (7.0, 10.0),
    "competition": (8.0, 12.0),
    "pre_course": (7.0, 10.0),
    "jour_course": (8.0, 12.0),
}

PROTEINES_G_PAR_KG = {
    "repos": (1.2, 1.4),
    "footing": (1.2, 1.4),
    "seuil": (1.4, 1.6),
    "fractionne": (1.6, 1.8),
    "sortie_longue": (1.4, 1.6),
    "trail": (1.4, 1.6),
    "competition": (1.4, 1.6),
    "pre_course": (1.4, 1.6),
    "jour_course": (1.4, 1.6),
}


def calculer_macros(
    poids_kg: float,
    type_seance: str,
    depense_totale_kcal: int,
    denivele_positif_m: int = 0,
    duree_min: int = 0,
    objectif_nutritionnel: str = "maintien",
) -> dict:
    """
    Calcule glucides, protéines et lipides pour la journée.

    Glucides et protéines en g/kg selon le type de séance (tables plus haut),
    lipides = calories restantes (minimum 20%).
    Ajustements : trail gros D+ → plus de protéines, effort >90min → plus de glucides,
    perte de poids → déficit 15%, prise de masse → surplus 10%.
    """

    # --- Ajustement selon l'objectif nutritionnel ---
    if objectif_nutritionnel == "perte_de_poids":
        calories_cible = round(depense_totale_kcal * 0.85)
    elif objectif_nutritionnel == "prise_de_masse":
        calories_cible = round(depense_totale_kcal * 1.10)
    else:
        calories_cible = depense_totale_kcal

    # --- Fourchettes de base ---
    g_range = GLUCIDES_G_PAR_KG.get(type_seance, (5.0, 7.0))
    p_range = PROTEINES_G_PAR_KG.get(type_seance, (1.4, 1.6))

    # --- Ajustements ---
    # Trail avec gros dénivelé : plus de protéines (dégâts musculaires en descente)
    if type_seance == "trail" and denivele_positif_m > 300:
        p_range = (1.6, 1.8)

    # Effort long (>90 min) : haut de la fourchette glucides
    if duree_min >= 90 and type_seance in ("sortie_longue", "trail"):
        g_range = (g_range[1] - 1, g_range[1])

    # Jour de course : moduler les glucides selon la durée de la course
    if type_seance == "jour_course":
        if duree_min <= 60:
            g_range = (5.0, 7.0)
        elif duree_min <= 120:
            g_range = (7.0, 9.0)
        else:
            g_range = (8.0, 12.0)

    # --- Calcul des grammes ---
    # On prend le milieu de la fourchette
    glucides_g = round(poids_kg * (g_range[0] + g_range[1]) / 2)
    proteines_g = round(poids_kg * (p_range[0] + p_range[1]) / 2)

    # Lipides : complètent les calories restantes (minimum 0.8 g/kg)
    cal_glucides = glucides_g * 4
    cal_proteines = proteines_g * 4
    cal_restantes = calories_cible - cal_glucides - cal_proteines
    lipides_g = round(max(cal_restantes / 9, poids_kg * 0.8))

    # --- Vérification : minimum 20% de lipides ---
    # On calcule le seuil à partir des calories cibles (pas du total recalculé)
    lipides_min_20pct = round(calories_cible * 0.20 / 9)
    if lipides_g < lipides_min_20pct:
        lipides_g = lipides_min_20pct

    return {
        "calories_cible_kcal": calories_cible,
        "glucides_g": glucides_g,
        "glucides_g_par_kg": round(glucides_g / poids_kg, 1),
        "proteines_g": proteines_g,
        "proteines_g_par_kg": round(proteines_g / poids_kg, 1),
        "lipides_g": lipides_g,
        "lipides_g_par_kg": round(lipides_g / poids_kg, 1),
    }



# 5. FONCTION PRINCIPALE POUR CALCULER LA JOURNÉE COMPLÈTE


def calculer_journee(profile: dict, session_params: dict) -> dict:
    """
    Fonction principale appelée par l'agent.
    Enchaîne : estimation distance → dépense séance → dépense totale → macros.
    """
    poids = profile["poids_kg"]
    type_seance = session_params.get("type_seance", "footing")
    duree = session_params.get("duree_min", 0)
    allure = session_params.get("allure_min_km")
    distance = session_params.get("distance_km")
    dp = session_params.get("denivele_positif_m", 0) or 0
    dn = session_params.get("denivele_negatif_m", 0) or 0

    # --- Distance ---
    if distance is None:
        distance = estimer_distance(duree, allure, type_seance)

    # --- Dépense séance ---
    depense_seance = calculer_depense_seance(
        poids_kg=poids,
        distance_km=distance,
        type_seance=type_seance,
        denivele_positif_m=dp,
        denivele_negatif_m=dn,
    )

    # --- Dépense totale ---
    depense_totale = calculer_depense_totale(
        depense_hors_entrainement_kcal=profile["depense_hors_entrainement_kcal"],
        depense_seance_kcal=depense_seance["depense_seance_kcal"],
    )

    # --- Macros ---
    macros = calculer_macros(
        poids_kg=poids,
        type_seance=type_seance,
        depense_totale_kcal=depense_totale,
        denivele_positif_m=dp,
        duree_min=duree,
        objectif_nutritionnel=profile.get("objectif_nutritionnel", "maintien"),
    )

    # --- Résumé lisible ---
    resume = (
        f"Type : {type_seance} | Distance : {distance} km | "
        f"Durée : {duree} min\n"
        f"D+ : {dp} m | D- : {dn} m | "
        f"Formule : {depense_seance['formule']}\n"
        f"Dépense séance : {depense_seance['depense_seance_kcal']} kcal "
        f"(coeff {depense_seance['coefficient']})\n"
        f"Dépense hors entraînement : "
        f"{profile['depense_hors_entrainement_kcal']} kcal\n"
        f"Dépense totale journée : {depense_totale} kcal"
    )

    return {
        "depense_seance": depense_seance,
        "depense_totale_kcal": depense_totale,
        "macros": macros,
        "resume": resume,
    }

