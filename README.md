# lightweight-extraction

L'objectif est de créer une interface simple permettant, à partir d'un faible
jeu de données annoté, de construire un pipeline d'extraction NER précis.

## Mock UI (Étape 1)

Ce dépôt contient actuellement un **mock** de l'Étape 1 de la roadmap
(voir [CLAUDE.md](CLAUDE.md)) : gestion des champs (titre, définition,
exemples) et upload PDF + NER, avec une **vraie persistance SQLite** mais des
outils externes (PyMuPDF4LLM, LangExtract) **entièrement simulés**. Voir
[specs/mock-ui.md](specs/mock-ui.md) pour la spec complète et
[tasks/plan.md](tasks/plan.md) / [tasks/todo.md](tasks/todo.md) pour le plan
d'implémentation.

## Prérequis

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Installation

```console
uv sync
```

## Lancer l'application

```console
uv run python -m app.main
```

L'app démarre sur http://localhost:5001 (rechargement automatique activé).
La base SQLite est créée automatiquement au premier lancement dans
`data/app.db`.

## Tests

```console
uv run pytest -v
```

Avec couverture :

```console
uv run pytest --cov=app --cov-report=term-missing
```
