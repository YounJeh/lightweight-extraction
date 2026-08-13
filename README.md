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
