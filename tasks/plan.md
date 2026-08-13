# Implementation Plan: Mock UI — Field Management & PDF Extraction

Spec de référence : [specs/mock-ui.md](../specs/mock-ui.md)

## Overview

Le repo est actuellement vide (pas de `pyproject.toml`, pas de code). On construit
une app FastHTML mono-utilisateur, avec persistance SQLite réelle des champs et
des runs d'extraction, mais des outils PDF/NER entièrement mockés derrière des
interfaces `Protocol` interchangeables. Le plan suit deux tranches verticales
(gestion des champs, puis extraction) posées sur une fondation commune
(scaffolding, schéma DB, modèles).

## Architecture Decisions

- **Pas d'ORM** — `sqlite3` standard + SQL paramétré, cohérent avec un mock
  volontairement simple (décision déjà actée dans la spec).
- **Repositories séparés** (`FieldRepository`, `ExtractionRunRepository`) plutôt
  qu'un repository générique, pour garder chaque couche CRUD testable
  indépendamment et refléter les deux agrégats du domaine.
- **Outils derrière `Protocol`** (`PdfTextExtractor`, `NerExtractor`) injectés
  dans les routes — permet de remplacer les mocks par PyMuPDF4LLM/LangExtract
  réels plus tard sans toucher `routes/`, `ui/`, `models.py` (critère de succès
  explicite de la spec).
- **Le fichier PDF n'est jamais persisté** — seul son nom (métadonnée) transite
  le temps de la requête ; c'est le run d'extraction qui est persisté, pas le
  document source.
- **Scaffolding avant toute tranche verticale** — le repo étant vide, une tâche
  de fondation (Task 1) est nécessaire avant de pouvoir slicer verticalement.

## Dependency Graph

```
Task 1: Scaffolding (pyproject, uv, app bootable)
    │
    ▼
Task 2: Schéma SQLite + modèles Pydantic + fixture DB de test
    │
    ├──▶ Task 3: FieldRepository (CRUD) ──▶ Task 4: Page/routes Champs (slice verticale 1)
    │
    └──▶ Task 5: Interfaces Protocol + Mock PDF/NER (indépendant de Task 3/4, parallélisable)
             │
             ▼
         Task 6: ExtractionRunRepository (persistance des runs)
             │
             ▼
         Task 7: Page/routes Extraction (slice verticale 2 — dépend de Task 4 pour la liste des champs disponibles)
             │
             ▼
Task 8: Navigation + layout partagé + états vides/erreurs
    │
    ▼
Task 9: Housekeeping (README, .gitignore, revue des critères de succès)
```

**Parallélisable** : Task 5 (outils mock) peut être fait en parallèle de
Task 3/4 (champs) une fois Task 1 posée — aucune dépendance entre les deux.

**Séquentiel obligatoire** : Task 2 avant tout (schéma partagé), Task 7 après
Task 4 (la page d'extraction lit la liste des champs existants) et après
Task 6 (persistance du run).

## Task List

### Phase 1: Foundation

- [ ] Task 1: Scaffolding du projet et app FastHTML démarrable
- [ ] Task 2: Schéma SQLite, modèles Pydantic et fixture de test DB

### Checkpoint: Foundation
- [ ] `uv run python -m app.main` démarre sans erreur
- [ ] `uv run pytest` passe (tests de création de schéma)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 2: Slice verticale — Gestion des champs

- [ ] Task 3: `FieldRepository` (CRUD) + tests unitaires
- [ ] Task 4: Page et routes "Champs" (liste, création, update, suppression)

### Checkpoint: Champs
- [ ] Créer/lister/modifier/supprimer un champ fonctionne de bout en bout dans le navigateur
- [ ] Un champ créé survit à un redémarrage du serveur (fichier SQLite)
- [ ] `uv run pytest` passe (repository + routes champs)

### Phase 3: Outils mockés

- [ ] Task 5: Interfaces `Protocol` + `MockPdfTextExtractor` + `MockNerExtractor` + tests unitaires

### Phase 4: Slice verticale — Extraction

- [ ] Task 6: `ExtractionRunRepository` (persistance des runs) + tests unitaires
- [ ] Task 7: Page et routes "Extraction" (upload PDF, sélection des champs, run mocké, persistance, affichage)

### Checkpoint: Extraction
- [ ] Upload PDF + sélection de champs + extraction simulée fonctionne de bout en bout dans le navigateur
- [ ] Le run d'extraction persiste et reste consultable après redémarrage
- [ ] Le fichier PDF source n'est jamais écrit durablement sur disque ou en DB
- [ ] `uv run pytest` passe (repository + routes extraction + outils mock)

### Phase 5: Polish

- [ ] Task 8: Navigation/sidebar partagée entre les deux pages, états vides et erreurs
- [ ] Task 9: Housekeeping (README, `.gitignore`, revue finale des critères de succès de la spec)

### Checkpoint: Complete
- [ ] Tous les critères de succès de `specs/mock-ui.md` sont cochés
- [ ] `uv run pytest` passe intégralement
- [ ] Parcours manuel complet (champs → extraction) validé dans le navigateur
- [ ] Revue finale avec l'utilisateur

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Upload multipart peut nécessiter `python-multipart` en dépendance explicite (non listée dans la stack CLAUDE.md) | Medium | À vérifier dès Task 1 ; si nécessaire, l'ajouter et le documenter comme dépendance technique de FastHTML (pas un nouvel outil métier), pas besoin de redemander validation. |
| FastHTML étant un framework jeune, l'API exacte (routing, gestion de formulaires/fichiers, injection de dépendances) peut différer de ce qui est esquissé dans la spec | Medium | Vérifier la doc FastHTML au moment de Task 1/4/7 (skill `source-driven-development` si besoin) plutôt que de deviner l'API. |
| Confusion possible entre résultat mock et résultat réel si le badge "mock" est oublié | Low | Couvert explicitement par un critère de succès et une règle "Toujours faire" dans la spec — vérifier à Task 7/8. |
| Le schéma DB de ce mock doit rester compatible avec l'Étape 2/3 à venir | Low (pour ce mock), Medium (long terme) | Garder le schéma simple et documenté ; toute évolution de schéma hors de ce plan doit repasser par la règle "Demander avant de faire" de la spec. |

## Open Questions

Aucune — la spec (`specs/mock-ui.md`) ne laisse plus de point bloquant ouvert.
