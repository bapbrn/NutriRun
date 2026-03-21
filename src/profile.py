"""
NutriRun — Module Profil Utilisateur

Charge le fichier profile.yaml, valide les données et calcule les valeurs dérivées (métabolisme de base, dépense quotidienne, etc.).

Ce module est la première brique de NutriRun : tous les autres modules (calculator, agent, prompts) dépendent du profil utilisateur.
"""

import os
import yaml



# 1. CHARGEMENT DU PROFIL


def load_profile(path: str = "profile.yaml") -> dict:
    """Charge le YAML du profil utilisateur."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Fichier '{path}' introuvable.\n"
            f"Copie le template et remplis-le avec tes informations :\n"
            f"  cp profile.yaml.example profile.yaml"
        )

    with open(path, "r", encoding="utf-8") as f:
        profile = yaml.safe_load(f)

    if not profile or not isinstance(profile, dict):
        raise ValueError(f"Le fichier '{path}' est vide ou mal formaté.")

    return profile



# 2. VALIDATION DES DONNÉES 


def validate_profile(profile: dict) -> list:
    """Vérifie la cohérence du profil. Retourne une liste d'erreurs (vide si ok)."""
    errors = []

    # --- Champs obligatoires ---
    required = ["sexe", "age", "poids_kg", "taille_cm"]
    for field in required:
        if field not in profile or profile[field] is None:
            errors.append(f"Champ obligatoire manquant : '{field}'")

    # Si des champs obligatoires manquent, pas la peine de continuer
    if errors:
        return errors

    # --- Sexe ---
    if profile["sexe"] not in ("homme", "femme"):
        errors.append(f"Sexe invalide : '{profile['sexe']}'. Valeurs acceptées : homme, femme")

    # --- Âge ---
    age = profile["age"]
    if not isinstance(age, (int, float)) or age < 10 or age > 100:
        errors.append(f"Âge invalide : {age}. Doit être entre 10 et 100 ans.")

    # --- Poids ---
    poids = profile["poids_kg"]
    if not isinstance(poids, (int, float)) or poids < 30 or poids > 200:
        errors.append(f"Poids invalide : {poids} kg. Doit être entre 30 et 200 kg.")

    # --- Taille ---
    taille = profile["taille_cm"]
    if not isinstance(taille, (int, float)) or taille < 120 or taille > 230:
        errors.append(f"Taille invalide : {taille} cm. Doit être entre 120 et 230 cm.")

    # --- Facteur d'activité ---
    facteur = profile.get("facteur_activite", 1.3)
    if not isinstance(facteur, (int, float)) or facteur < 1.0 or facteur > 2.0:
        errors.append(
            f"Facteur d'activité invalide : {facteur}. "
            f"Doit être entre 1.0 (sédentaire) et 2.0 (très actif)."
        )

    # --- Régime ---
    regime = profile.get("regime", "omnivore")
    valid_regimes = ["omnivore", "vegetarien", "vegan", "sans_gluten", "sans_lactose"]
    if regime not in valid_regimes:
        errors.append(f"Régime invalide : '{regime}'. Valeurs acceptées : {valid_regimes}")

    # --- Objectif nutritionnel ---
    objectif = profile.get("objectif_nutritionnel", "maintien")
    valid_objectifs = ["maintien", "perte_de_poids", "prise_de_masse"]
    if objectif not in valid_objectifs:
        errors.append(
            f"Objectif nutritionnel invalide : '{objectif}'. "
            f"Valeurs acceptées : {valid_objectifs}"
        )

    # --- Objectif date (optionnel, mais si présent doit être ISO 8601) ---
    objectif_date = profile.get("objectif_date", "")
    if objectif_date:
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", objectif_date):
            errors.append(
                f"Format de date invalide : '{objectif_date}'. "
                f"Utilise le format YYYY-MM-DD (ex: 2026-06-13)."
            )

    # --- VMA (optionnel mais si présent, doit être cohérent) ---
    vma = profile.get("vma_kmh")
    if vma is not None and (not isinstance(vma, (int, float)) or vma < 8 or vma > 25):
        errors.append(f"VMA invalide : {vma} km/h. Doit être entre 8 et 25 km/h.")

    # --- FCmax (optionnel) ---
    fcmax = profile.get("fcmax_bpm")
    if fcmax is not None and (not isinstance(fcmax, (int, float)) or fcmax < 140 or fcmax > 230):
        errors.append(f"FCmax invalide : {fcmax} bpm. Doit être entre 140 et 230 bpm.")

    return errors



# 3. CALCUL DES VALEURS DÉRIVÉES


def compute_metabolisme_base(sexe: str, poids_kg: float, taille_cm: float, age: int) -> float:
    """Métabolisme de base — formule de Harris-Benedict révisée."""
    if sexe == "homme":
        mb = 88.362 + (13.397 * poids_kg) + (4.799 * taille_cm) - (5.677 * age)
    else:
        mb = 447.593 + (9.247 * poids_kg) + (3.098 * taille_cm) - (4.330 * age)

    return round(mb)


def build_complete_profile(raw_profile: dict) -> dict:
    """Prend le profil brut et ajoute les valeurs calculées (MB, dépense, FCmax par défaut, etc.)."""
    profile = dict(raw_profile)

    # --- Métabolisme de base ---
    profile["metabolisme_base_kcal"] = compute_metabolisme_base(
        sexe=profile["sexe"],
        poids_kg=profile["poids_kg"],
        taille_cm=profile["taille_cm"],
        age=profile["age"],
    )

    # --- Dépense quotidienne hors entraînement ---
    facteur = profile.get("facteur_activite", 1.3)
    profile["depense_hors_entrainement_kcal"] = round(
        profile["metabolisme_base_kcal"] * facteur
    )

    # --- FCmax (si non renseignée : formule 220 - âge) ---
    if not profile.get("fcmax_bpm"):
        profile["fcmax_bpm"] = 220 - profile["age"]

    # --- VMA (si non renseignée mais VO2max disponible) ---
    if not profile.get("vma_kmh") and profile.get("vo2max"):
        profile["vma_kmh"] = round(profile["vo2max"] / 3.5, 1)

    # --- Valeurs par défaut pour les champs optionnels ---
    profile.setdefault("regime", "omnivore")
    profile.setdefault("allergies", [])
    profile.setdefault("aliments_exclus", [])
    profile.setdefault("seances_par_semaine", 4)
    profile.setdefault("objectif_nutritionnel", "maintien")
    profile.setdefault("objectif_course", "")
    profile.setdefault("objectif_date", "")
    profile.setdefault("objectif_distance_km", 0)
    profile.setdefault("objectif_denivele_m", 0)

    return profile



# 4. FONCTION PRINCIPALE D'INITIALISATION DU PROFIL


def init_profile(path: str = "profile.yaml") -> dict:
    """Charge, valide et complète le profil. C'est le point d'entrée pour les autres modules."""
    # Charger
    raw = load_profile(path)

    # Valider
    errors = validate_profile(raw)
    if errors:
        error_msg = "Erreurs dans le profil :\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    # Compléter avec les calculs
    profile = build_complete_profile(raw)

    # Afficher un résumé
    print("=" * 50)
    print("👤 Profil chargé")
    print("=" * 50)
    print(f"  {profile['sexe'].capitalize()}, {profile['age']} ans, "
          f"{profile['poids_kg']}kg, {profile['taille_cm']}cm")
    print(f"  Métabolisme de base : {profile['metabolisme_base_kcal']} kcal/jour")
    print(f"  Dépense hors entraînement : {profile['depense_hors_entrainement_kcal']} kcal/jour")
    if profile.get("vma_kmh"):
        print(f"  VMA : {profile['vma_kmh']} km/h")
    print(f"  Régime : {profile['regime']}")
    if profile.get("objectif_course"):
        print(f"  Objectif : {profile['objectif_course']}")
    print("=" * 50)

    return profile