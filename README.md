# 🏃 NutriRun

**Agent nutritionnel intelligent pour coureurs de trail et de route.**

Décris ta séance en langage naturel — NutriRun génère un plan alimentaire personnalisé pour ta journée : repas concrets avec quantités, macros calculés, conseils d'hydratation et recettes adaptées.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agent-blue)
![Ollama](https://img.shields.io/badge/Ollama-LLM-000000?logo=ollama)
![FAISS](https://img.shields.io/badge/FAISS-RAG-yellow)
![Gradio](https://img.shields.io/badge/Gradio-Interface-FF7C00?logo=gradio)
![Strava](https://img.shields.io/badge/Strava-API-FC4C02?logo=strava&logoColor=white)

> **Projet universitaire** — Cours d'IA Générative, Université Paris Dauphine, 2025-2026.
> Professeur : Théo Lopès Quintas.

---

## Fonctionnalités

**Décris ta séance, reçois ton plan.** Écris simplement "Footing 45min à 5:00/km ce matin" ou "Trail 2h 600D+ dimanche" — l'agent comprend ta séance et génère un plan alimentaire complet pour la journée : 3 repas + 1 collation, avec les quantités en grammes et les macros détaillés.

**Détection automatique du mode.** L'agent analyse ton texte et détecte s'il s'agit d'un entraînement classique, d'une journée de repos, d'une préparation de course à venir, ou d'un jour de compétition — et adapte le plan en conséquence.

**Calculs personnalisés.** Dépense calorique, besoins en glucides/protéines/lipides : tout est calculé à partir de ton profil (poids, âge, taille) et des paramètres de ta séance (durée, intensité, dénivelé).

**Base de connaissances nutrition sportive.** L'agent s'appuie sur 10 fichiers de référence (dont les fiches officielles de l'INSEP) pour ses recommandations : timing nutritionnel, recettes sportives, protocoles pré-course, stratégies jour de course.

**Calibration avec Strava** (optionnel). Connecte ton compte Strava : l'agent retrouve tes séances similaires dans ton historique et ajuste les estimations caloriques en comparant les données de ta montre aux formules théoriques.

**Profil personnalisable.** Ton âge, poids, régime alimentaire, allergies, aliments exclus, objectif course — tout se configure dans un simple fichier YAML.

**Ajuste le plan à ta guise.** Tu peux préciser des préférences à la saisie ("plutôt sucré ce matin", "pas le temps de cuisiner") et demander des modifications après génération ("remplace le saumon", "plus de glucides au petit-déj").

---

## Architecture de l'agent

NutriRun est un agent LangGraph à **14 nœuds**. Le LLM intervient à 3 étapes clés (parsing, routage, génération) — tout le reste est déterministe.

```
Texte libre
    │
    ▼
┌─────────┐     ┌─────────────┐     ┌────────────┐     ┌────────────┐
│ PARSING │────▶│ PREFERENCES │────▶│ VALIDATION │────▶│   REPAIR   │
│  (LLM)  │     │             │     │  (règles)  │  ◀──│   (LLM)    │
└─────────┘     └─────────────┘     └─────┬──────┘     └────────────┘
                                          │ ✓ valide
                                          ▼
                                   ┌─────────────┐
                                   │   ROUTEUR   │  ← Décide quels outils activer
                                   │    (LLM)    │     selon le contexte de la séance
                                   └──────┬──────┘
                                          │
                    ┌─────────────────────┼──────────────────────┐
                    ▼                     ▼                      ▼
              ┌──────────┐    ┌───────────────────────┐    ┌────────────┐
              │  CALCUL  │    │      RAG × 5          │    │  STRAVA    │
              │(formules)│    │ timing · recettes ·    │    │(optionnel) │
              │          │    │ nutrition · pré-course │    │            │
              └────┬─────┘    │ · jour de course      │    └─────┬──────┘
                   │          └───────────┬───────────┘          │
                   └──────────────────────┼──────────────────────┘
                                          │  ← Exécution en parallèle (fan-out/fan-in)
                                          ▼
                                   ┌─────────────┐
                                   │    MERGE    │  Calibration Strava + macros finaux
                                   └──────┬──────┘
                                          ▼
                                   ┌─────────────┐
                                   │ GENERATION  │  Prompt adapté au mode détecté
                                   │    (LLM)    │
                                   └──────┬──────┘
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                        ✅ Résultat           🔄 Régénération
                                              avec feedback
                                              (repasse par GENERATION)
```

### Les 4 modes du routeur

| Mode | Outils activés |
|------|----------------|
| **Repos** | RAG recettes uniquement |
| **Entraînement** | Calcul + Strava + RAG timing/recettes/nutrition |
| **Pré-course** | Tout le mode entraînement + RAG pré-compétition |
| **Jour de course** | RAG jour de course + timing + recettes + Strava |

---

## Installation

### Prérequis

- **Python 3.10+**
- **Ollama** installé et lancé ([ollama.com](https://ollama.com))
- Un modèle Ollama disponible (par défaut `gpt-oss:120b-cloud`, ou `gemma3:4b` en local)

### Étapes

```bash
# 1. Cloner le repo
git clone https://github.com/bapbrn/NutriRun.git
cd NutriRun

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer ton profil
cp profile.yaml.example profile.yaml
# Édite profile.yaml avec tes infos (âge, poids, taille, régime, etc.)

# 4. (Optionnel) Configurer Strava
cp .env.example .env
# Remplis les clés API Strava dans .env

# 5. Lancer Ollama (doit tourner en arrière-plan)
ollama serve

# 6. Lancer l'app
python app.py
```

L'interface s'ouvre sur [http://localhost:7860](http://localhost:7860).

### Changer de modèle LLM

Le modèle est défini dans `app.py` à la ligne `init_agent(profile, model_name="gpt-oss:120b-cloud")`. Pour utiliser un modèle local :

```python
agent, _, _, _ = init_agent(profile, model_name="gemma3:4b")
```

---

## Configuration

### Profil utilisateur (`profile.yaml`)

```yaml
# Données physiques
sexe: "homme"              # homme / femme
age: 25
poids_kg: 70
taille_cm: 175

# Entraînement
vma_kmh: 15.0              # optionnel
fcmax_bpm: 195             # optionnel (sinon 220 - âge)
seances_par_semaine: 4

# Mode de vie (hors entraînement)
facteur_activite: 1.3      # entre 1.0 (sédentaire) et 2.0 (très actif)

# Préférences alimentaires
regime: "omnivore"         # omnivore / vegetarien / vegan / sans_gluten / sans_lactose
allergies: []              # ex: ["arachides", "fruits de mer"]
aliments_exclus: []        # ex: ["brocoli", "tofu"]

# Objectif course (optionnel)
objectif_course: ""        # ex: "Marathon de Paris"
objectif_date: ""          # ex: "2026-06-13"
objectif_distance_km: 0
objectif_denivele_m: 0

# Objectif nutritionnel
objectif_nutritionnel: "maintien"  # maintien / perte_de_poids / prise_de_masse
```

### Strava (`.env`, optionnel)

```
STRAVA_CLIENT_ID=ton_client_id
STRAVA_CLIENT_SECRET=ton_client_secret
STRAVA_ACCESS_TOKEN=ton_access_token
STRAVA_REFRESH_TOKEN=ton_refresh_token
```

Les tokens se créent sur [strava.com/settings/api](https://www.strava.com/settings/api). Le refresh est automatique (les access tokens expirent toutes les 6 heures).

---

## Structure du projet

```
NutriRun/
├── app.py                          # Interface Gradio + point d'entrée
├── profile.yaml.example            # Template profil utilisateur
├── .env.example                    # Template config Strava
├── requirements.txt                # Dépendances (compatibles Mac Intel)
├── README.md
│
├── src/
│   ├── agent.py                    # Graphe LangGraph 14 nœuds, routeur LLM
│   ├── profile.py                  # Chargement profil YAML, Harris-Benedict
│   ├── calculator.py               # Calculs déterministes (dépense, macros)
│   ├── rag.py                      # Pipeline RAG (FAISS + all-MiniLM-L6-v2)
│   ├── strava.py                   # OAuth Strava, similarité, calibration
│   └── prompts.py                  # 6 prompts centralisés
│
├── knowledge_base/                 # Base de connaissances RAG
│   ├── 00_INSEP_fiches_nutrition.pdf
│   ├── 01_fondamentaux_nutrition.md
│   ├── 02_timing_nutritionnel.md
│   ├── 03_types_seances.md
│   ├── 04_plans_alimentaires_types.md
│   ├── 05_considerations_speciales.md
│   ├── 06_nutrition_trail.md
│   ├── 07_precompetition.md
│   ├── 08_jour_de_course.md
│   └── 09_recettes_sportives.md
│
└── faiss_index/                    # Cache FAISS (généré automatiquement)
```

---

## Modules

### `agent.py` — Agent LangGraph

Cœur du projet. Définit les modèles Pydantic (`TrainingSession`, `RouterDecision`), les 14 nœuds du graphe, le routeur LLM avec fallback, et les fonctions `init_agent()` / `run_agent()`. Les nœuds outils (calcul, Strava, RAG) s'exécutent en parallèle après le routeur (fan-out/fan-in). Le graphe est compilé une seule fois au démarrage.

### `calculator.py` — Calculs déterministes

Estimation de distance, dépense calorique (formule route + formule trail avec coefficients Minetti D+/D-), et besoins en macros (tables g/kg ajustées selon la durée, le dénivelé et l'objectif nutritionnel).

### `rag.py` — Pipeline RAG

Chargement markdown + PDF → chunking → vectorisation FAISS avec `all-MiniLM-L6-v2` → retriever `k=5`. L'index FAISS est persisté sur disque et reconstruit automatiquement si la knowledge base change. Chaque nœud RAG fait 2 requêtes et déduplique les résultats.

### `strava.py` — Intégration Strava

OAuth avec refresh automatique du token, récupération des activités Run/TrailRun, recherche par score de similarité (durée + dénivelé), calibration calorique via les calories montre ou estimation par fréquence cardiaque (formule de Keytel 2005).

### `profile.py` — Profil utilisateur

Charge et valide le YAML, calcule le métabolisme de base (Harris-Benedict révisée) et la dépense hors entraînement.

### `prompts.py` — Prompts centralisés

6 prompts : parsing, repair, router, génération entraînement, génération pré-course, génération jour de course.

---

## Base de connaissances

| Fichier | Contenu |
|---------|---------|
| `00_INSEP_fiches_nutrition.pdf` | Fiches officielles INSEP (assiette du sportif, top aliments, hydratation) |
| `01_fondamentaux_nutrition.md` | Macronutriments, hydratation, micronutriments, aliments protecteurs |
| `02_timing_nutritionnel.md` | Quand manger avant/pendant/après l'effort |
| `03_types_seances.md` | Besoins spécifiques par type de séance |
| `04_plans_alimentaires_types.md` | Plans alimentaires exemples |
| `05_considerations_speciales.md` | Régimes spéciaux, femmes, chaleur, altitude |
| `06_nutrition_trail.md` | Ravitaillement trail/ultra, train the gut |
| `07_precompetition.md` | Protocole J-7 à J-1, charge glucidique progressive |
| `08_jour_de_course.md` | Petit-déj, ravitaillement par durée, récupération |
| `09_recettes_sportives.md` | Recettes avec macros détaillés |

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| LLM | Ollama (`gpt-oss:120b-cloud` ou `gemma3:4b`) via `langchain-ollama` |
| Agent | LangGraph (graphe d'états, 14 nœuds, fan-out/fan-in) |
| RAG | FAISS + `all-MiniLM-L6-v2` (HuggingFace) |
| Validation | Pydantic v2 |
| Interface | Gradio 4+ (thème custom) |
| API externe | Strava (optionnel) |
| Profil | YAML + `pyyaml` |

---

## Crédits

Projet réalisé dans le cadre du cours **IA Générative** à l'**Université Paris Dauphine** (2025-2026).

Professeur : **Théo Lopès Quintas**

Sources : fiches nutrition de l'**INSEP**, formule de Harris-Benedict révisée, coefficients de Minetti, formule de Keytel et al. (2005).
