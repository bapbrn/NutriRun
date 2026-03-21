"""
NutriRun — Module Strava

Gestion de l'API Strava : 
1) authentification OAuth avec refresh automatique du token
2) récupération des activités
3)recherche de séances similaires et calcul du facteur de calibration calorique.

Ce module est optionnel. Si Strava n'est pas configuré, l'agent fonctionne avec les formules théoriques seules calculées dans calculator.py. 
"""

import os
import time
import requests
from dotenv import load_dotenv, set_key

load_dotenv()


# 1. AUTHENTIFICATION ET GESTION DES TOKENS STRAVA

def get_strava_config() -> dict:
    return {
        "client_id": os.environ.get("STRAVA_CLIENT_ID", ""),
        "client_secret": os.environ.get("STRAVA_CLIENT_SECRET", ""),
        "access_token": os.environ.get("STRAVA_ACCESS_TOKEN", ""),
        "refresh_token": os.environ.get("STRAVA_REFRESH_TOKEN", ""),
    }


def is_strava_configured() -> bool:
    config = get_strava_config()
    return bool(
        config["access_token"]
        and config["refresh_token"]
        and config["client_secret"]
    )


_token_expires_at = 0


def refresh_access_token() -> str:
    """Refresh le token Strava (expire toutes les 6h) et met à jour le .env."""
    global _token_expires_at
    config = get_strava_config()

    if not config["refresh_token"] or not config["client_secret"]:
        return ""

    try:
        response = requests.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": config["refresh_token"],
            },
        )
        response.raise_for_status()
        data = response.json()

        new_access = data["access_token"]
        new_refresh = data["refresh_token"]
        _token_expires_at = data.get("expires_at", 0)

        # Mettre à jour en mémoire
        os.environ["STRAVA_ACCESS_TOKEN"] = new_access
        os.environ["STRAVA_REFRESH_TOKEN"] = new_refresh

        # Mettre à jour le fichier .env si il existe
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            set_key(env_path, "STRAVA_ACCESS_TOKEN", new_access)
            set_key(env_path, "STRAVA_REFRESH_TOKEN", new_refresh)

        print("  Strava : token rafraîchi")
        return new_access

    except Exception as e:
        print(f"  Strava : erreur refresh — {e}")
        return ""


def get_valid_token() -> str:
    """Retourne un token valide — refresh si expiré."""
    global _token_expires_at
    config = get_strava_config()
    token = config["access_token"]

    if not token:
        return refresh_access_token()

    # Si on connaît le timestamp d'expiration, on l'utilise
    if _token_expires_at > 0:
        if time.time() < _token_expires_at - 60:
            return token
        else:
            return refresh_access_token()

    # Premier appel : on ne connaît pas l'expiration, on teste via API
    try:
        r = requests.get(
            "https://www.strava.com/api/v3/athlete",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if r.status_code == 200:
            return token
        elif r.status_code == 401:
            return refresh_access_token()
        else:
            return ""
    except requests.exceptions.RequestException:
        return ""


# 2. RÉCUPÉRATION DES ACTIVITÉS 

def get_recent_activities(n: int = 50) -> list:
    """Récupère les n dernières activités Run/TrailRun depuis l'API Strava."""
    token = get_valid_token()
    if not token:
        return []

    try:
        response = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {token}"},
            params={"per_page": n, "page": 1},
            timeout=10,
        )
        response.raise_for_status()
        activities = response.json()

        runs = [a for a in activities if a.get("type") in ("Run", "TrailRun")]
        print(f"  Strava : {len(runs)} activités de course récupérées")
        return runs

    except Exception as e:
        print(f"  Strava : erreur récupération — {e}")
        return []


# 3. Recherche de séances similaires

def find_similar_sessions(
    activities: list,
    duree_min: int,
    denivele_m: int = 0,
    max_results: int = 5,
) -> list:
    """
    Trouve les séances Strava les plus proches de la séance décrite.
    Score = différence de durée (×0.6) + différence de D+ (×0.4). Plus bas = plus similaire.
    """
    scored = []

    for act in activities:
        act_duree = act.get("moving_time", 0) / 60
        act_distance = act.get("distance", 0) / 1000
        act_dp = act.get("total_elevation_gain", 0)
        act_calories = act.get("calories", 0)

        # Score de similarité (plus bas = plus similaire)
        duree_diff = abs(act_duree - duree_min) / max(duree_min, 1)
        dp_diff = abs(act_dp - denivele_m) / max(denivele_m, 100)

        # Pondération : la durée est plus importante que le dénivelé
        score = duree_diff * 0.6 + dp_diff * 0.4

        scored.append({
            "date": act.get("start_date_local", "")[:10],
            "name": act.get("name", ""),
            "distance_km": round(act_distance, 1),
            "duree_min": round(act_duree),
            "denivele_m": round(act_dp),
            "calories_montre": round(act_calories) if act_calories else None,
            "fc_moyenne": act.get("average_heartrate"),
            "fc_max": act.get("max_heartrate"),
            "score_similarite": round(score, 3),
        })

    # Trier par score et prendre les meilleurs
    scored.sort(key=lambda x: x["score_similarite"])
    return scored[:max_results]


# 4. CALCUL DU FACTEUR DE CALIBRATION CALORIQUE

def estimate_calories_from_hr(fc_moyenne: float, duree_min: int, poids_kg: float, age: int, sexe: str = "homme") -> float:
    """Estimation calories via FC moyenne — formule de Keytel et al. (2005)."""
    if sexe == "homme":
        kcal_par_min = (-55.0969 + 0.6309 * fc_moyenne + 0.1988 * poids_kg + 0.2017 * age) / 4.184
    else:
        kcal_par_min = (-20.4022 + 0.4472 * fc_moyenne - 0.1263 * poids_kg + 0.074 * age) / 4.184

    return max(kcal_par_min * duree_min, 0)


def compute_calibration_factor(
    similar_sessions: list,
    poids_kg: float,
    age: int = 25,
    sexe: str = "homme",
) -> float:
    """
    Compare les calories réelles (montre ou estimation FC) aux calories théoriques
    pour calculer un facteur de calibration. Borné entre 0.7 et 1.5.
    """
    if not similar_sessions:
        return 1.0

    ratios = []
    for s in similar_sessions:
        distance = s["distance_km"]
        dp = s["denivele_m"]

        # Calories réelles : montre ou estimation FC
        calories_reelles = None
        if s.get("calories_montre") and s["calories_montre"] > 0:
            calories_reelles = s["calories_montre"]
        elif s.get("fc_moyenne") and s["fc_moyenne"] > 0:
            calories_reelles = estimate_calories_from_hr(
                fc_moyenne=s["fc_moyenne"],
                duree_min=s["duree_min"],
                poids_kg=poids_kg,
                age=age,
                sexe=sexe,
            )

        if not calories_reelles or calories_reelles <= 0:
            continue

        # Dépense théorique (même formule que calculator.py)
        # Strava ne fournit pas le D- dans le listing d'activités,
        # on utilise le D+ comme approximation du D-
        if dp > 0:
            theorique = poids_kg * (distance * 1.0 + dp * 0.005 + dp * 0.002)
        else:
            theorique = poids_kg * distance * 1.0

        if theorique > 0:
            ratios.append(calories_reelles / theorique)

    if not ratios:
        return 1.0

    # Moyenne des ratios, bornée entre 0.7 et 1.5
    calibration = sum(ratios) / len(ratios)
    calibration = max(0.7, min(1.5, calibration))

    return round(calibration, 3)

####