# lightweight-extraction

L'objectif est de créer une interface simple permettant, à partir d'un faible
jeu de données annoté, de construire un pipeline d'extraction NER précis.

## Étape 1 : gestion des champs + extraction PDF/NER réelle

Ce dépôt implémente l'Étape 1 de la roadmap (voir [CLAUDE.md](CLAUDE.md)) :
gestion des champs (titre, définition, exemples), upload PDF, et extraction
NER — le tout avec une **vraie persistance SQLite** et des outils PDF/NER
**réels** (PyMuPDF4LLM + LangExtract/Gemini). Le mock initial
([specs/mock-ui.md](specs/mock-ui.md)) a été remplacé par l'implémentation
décrite dans [specs/pdf-ner-real.md](specs/pdf-ner-real.md) (plan :
[tasks/plan-pdf-ner-real.md](tasks/plan-pdf-ner-real.md) /
[tasks/todo-pdf-ner-real.md](tasks/todo-pdf-ner-real.md)).

## Prérequis

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Installation

```console
uv sync
```

## Configuration

Copier `.env.example` en `.env` et renseigner une clé API Gemini gratuite
(https://aistudio.google.com) :

```console
cp .env.example .env
```

```
GOOGLE_GENERATIVE_AI_API_KEY=...   # requis pour l'extraction NER réelle
LLM_MODEL=                          # vide = défaut LangExtract (gemini-3.5-flash)
```

Sans clé API, l'app démarre et la gestion des champs fonctionne normalement ;
seule une extraction (`POST /extraction`) échouera.

### Tracing Langfuse (optionnel)

Pour voir chaque extraction (texte source, résultat, latence, erreurs) dans
un dashboard [Langfuse Cloud](https://cloud.langfuse.com), créer un projet
Langfuse puis renseigner ses clés dans `.env` :

```
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_BASE_URL=                  # vide = région EU (cloud.langfuse.com)
```

Sans ces deux clés, aucune trace n'est envoyée (`NoOpTracer`, comportement
par défaut). Une fois configurées, chaque extraction apparaît dans le
dashboard Langfuse sous le nom `ner_extraction`, avec le texte source en
input, le résultat en output, et provider/modèle/champs/nom de fichier en
tags et metadata.

## Lancer l'application

```console
uv run python -m app.main
```

L'app démarre sur http://localhost:5001 (rechargement automatique activé).
La base SQLite est créée automatiquement au premier lancement dans
`data/app.db`.

## Tests

Suite par défaut (aucun réseau, aucune clé API requise) :

```console
uv run pytest -v -m "not live"
```

Avec couverture :

```console
uv run pytest --cov=app --cov-report=term-missing -m "not live"
```

Test d'intégration réel (appelle le vrai modèle Gemini via LangExtract —
nécessite une clé API valide dans `.env`) :

```console
uv run pytest -v -m live
```

## Mise à jour totale de la DB
```console
uv run python scripts/reset_db.py
```

## Éval du pipeline sur le dataset gold

Rejoue le pipeline d'extraction réel (PDF → NER) sur le dataset gold versionné
([tests/data/dataset_gold_devis.yaml](tests/data/dataset_gold_devis.yaml)) et
trace précision/recall/F1 par champ, latence et grounding dans un Dataset
Langfuse `gold-devis`, comparable d'un run à l'autre — voir
[specs/ci-eval-gold-dataset.md](specs/ci-eval-gold-dataset.md) pour la spec
complète.

En local (nécessite les clés Gemini + Langfuse dans `.env`) :

```console
uv run python scripts/gold_dataset_sync.py   # sync YAML -> Dataset Langfuse
uv run python scripts/gold_dataset_eval.py   # rejoue le pipeline + scores
```

En CI : workflow GitHub Actions
[eval-gold-dataset.yml](.github/workflows/eval-gold-dataset.yml), déclenché
manuellement (`workflow_dispatch`, onglet Actions), avec un champ `llm_model`
optionnel pour comparer des modèles sans changer de code. Secrets de repo
requis (`Settings > Secrets and variables > Actions`) :
`GOOGLE_GENERATIVE_AI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_BASE_URL`. Résultats consultables dans l'UI Langfuse (Datasets >
`gold-devis` > Runs) et dans le résumé du run GitHub Actions.

Reporting seul pour l'instant, pas de gate bloquant — le dataset gold est
encore petit (14 documents). Le coût par appel Gemini n'est pas mesurable
avec l'instrumentation actuelle (LangExtract n'expose pas l'usage token).

## Déploiement Cloud Run

L'app est déployable sur [Cloud Run](https://cloud.google.com/run) (projet
GCP `extraction-pv`, région `europe-west9`) — voir
[specs/deploy-cloud-run.md](specs/deploy-cloud-run.md) pour la spec complète.

Service actuel : `https://extraction-pv-783442504013.europe-west9.run.app`

**Accès protégé par Basic Auth** (identifiants communiqués séparément, jamais
committés) — un lien partageable sans compte Google, pas l'auth IAM native de
Cloud Run.

**Persistance éphémère** : la base SQLite vit dans le système de fichiers du
conteneur. Chaque redémarrage (scale-to-zero, redéploiement, OOM) repart avec
une base vide — comportement accepté pour un usage démo ponctuel, pas de
persistance durable (Cloud SQL/GCS) mise en place.

Redéploiement (buildpacks, pas de Dockerfile) :

```console
gcloud run deploy extraction-pv \
  --source . \
  --region europe-west9 \
  --project extraction-pv \
  --allow-unauthenticated \
  --set-env-vars=LLM_MODEL=gpt-4o-mini \
  --set-build-env-vars="GOOGLE_ENTRYPOINT=python -m app.main" \
  --set-secrets=GOOGLE_GENERATIVE_AI_API_KEY=google-generative-ai-api-key:latest,OPENAI_API_KEY=openai-api-key:latest,LANGFUSE_PUBLIC_KEY=langfuse-public-key:latest,LANGFUSE_SECRET_KEY=langfuse-secret-key:latest,BASIC_AUTH_USER=basic-auth-user:latest,BASIC_AUTH_PASSWORD=basic-auth-password:latest
```

Secrets gérés dans [Secret Manager](https://cloud.google.com/secret-manager)
du projet `extraction-pv` (`google-generative-ai-api-key`, `openai-api-key`,
`langfuse-public-key`, `langfuse-secret-key`, `basic-auth-user`,
`basic-auth-password`) — pour mettre à jour une valeur :

```console
printf '%s' 'nouvelle-valeur' | gcloud secrets versions add <nom-du-secret> --data-file=- --project=extraction-pv
```

(`printf` sans retour à la ligne final — un `\n` parasite dans un secret casse
une comparaison stricte, ex. le Basic Auth.)


