# Implementation Plan: CI d'évaluation du pipeline sur le dataset gold

Spec de référence : [specs/ci-eval-gold-dataset.md](../specs/ci-eval-gold-dataset.md) ·
Cadrage initial : [docs/ideas/ci-eval-gold-dataset.md](../docs/ideas/ci-eval-gold-dataset.md)

## Overview

Deux scripts autonomes (`scripts/gold_dataset_sync.py`,
`scripts/gold_dataset_eval.py`), rejouant le pipeline de production réel sur
le dataset gold via le SDK Langfuse (`Dataset`/`run_experiment`), puis un
workflow GitHub Actions `workflow_dispatch` qui les exécute. Chaîne
majoritairement séquentielle : d'abord régler l'intégrité des données (PDF
manquant), puis les fondations git (PDF committés, définitions de champs
git-trackées), puis la sync Langfuse, puis le pipeline + évaluateurs, puis le
branchement CI.

## Architecture Decisions

- **Aucune réimplémentation du pipeline.** `scripts/gold_dataset_eval.py`
  importe et appelle directement `PyMuPDF4LlmTextExtractor.extract_text` et
  `LangExtractNerExtractor.extract` — le `task` passé à
  `dataset.run_experiment(...)` est un wrapper fin autour de ces deux appels,
  pas une réécriture. Ça garantit que le score mesuré est celui du pipeline
  réellement servi par l'app, pas d'un chemin parallèle qui pourrait diverger
  (risque classique de "eval/prod skew").
- **Les définitions des 6 champs gold vivent en git, indépendamment de
  `data/app.db`.** `data/app.db` contient aujourd'hui ces 6 champs (vérifié :
  `numero_devis`, `nom_societe`, `pourcentage_acompte`, `pourcentage_solde`,
  `delai_paiement_solde_jours`, `duree_validite_offre`), mais ce fichier est
  gitignoré (`*.db`) et éphémère (recréé vide par `scripts/reset_db.py`,
  perdu à chaque redémarrage Cloud Run) — un runner CI frais ne l'a pas. Un
  nouveau fixture `tests/data/gold_devis_fields.csv`, au même format que
  `DATASET GOLD.csv` (colonnes attendues par
  `app/fields_import.py::REQUIRED_COLUMNS`), extrait des 6 lignes
  actuellement en base, est committé. `gold_dataset_eval.py` seed une base
  SQLite jetable (`tempfile`, jamais `data/app.db`) via `init_db` +
  `FieldRepository.upsert_by_key` à partir de ce CSV — réutilise
  `app.fields_import.import_fields` tel quel pour le parsing, aucune nouvelle
  logique de parsing de champs.
- **Le YAML git reste la seule source de vérité éditable** (déjà tranché en
  idéation). `gold_dataset_sync.py` upsert des items dans le Dataset Langfuse
  `gold-devis` par `document_id` (clé unique confirmée après correction du
  doublon `document_id` 2/3) à chaque exécution — le Dataset Langfuse est un
  miroir recalculé, jamais édité à la main côté Langfuse.
- **Matching normalisé réutilise `app/tools/type_coercion.py`**, pas de
  nouvelles règles de parsing dupliquées. `scripts/gold_matching.py` s'appuie
  sur les mêmes conversions (`int`, `float`, `date.fromisoformat`) que
  l'app pour décider qu'une valeur extraite correspond à la valeur gold —
  seule la logique de *comparaison* (égalité/tolérance après conversion) est
  nouvelle. Si `_TRUE_TOKENS`/`_FALSE_TOKENS` (actuellement privés dans
  `type_coercion.py`) sont nécessaires pour le matching `bool`, ils sont
  remontés au niveau module plutôt que recopiés.
- **Convention slot-filling standard pour TP/FP/FN** : une valeur extraite
  incorrecte compte comme 1 FP (valeur produite à tort) *et* 1 FN (la bonne
  valeur n'a pas été produite) — pas seulement "faux". Gold `null` +
  extraction non vide → FP seul. Gold non vide + extraction vide → FN seul.
  Gold `null` + extraction vide → TN, exclu du calcul P/R (convention
  standard, évite de gonfler artificiellement le score avec des champs
  absents des deux côtés).
- **`human_validation: false` exclus des métriques "headline" par
  agrégation, pas par filtrage de la sync.** Le Dataset Langfuse contient
  toujours tous les documents (traçabilité complète, comparaison future
  possible si un jour tous les documents sont validés) ; c'est l'évaluateur
  run-level qui calcule deux jeux de scores (validés vs tous) et n'expose le
  premier comme score "principal" — décision différée à l'implémentation
  entre deux Datasets Langfuse séparés vs un seul avec filtrage par
  métadonnée (Task 6, à vérifier selon ce que l'API `run_experiment` permet
  facilement).
- **CI = mêmes scripts qu'en local, pas de logique dupliquée dans le YAML du
  workflow.** `.github/workflows/eval-gold-dataset.yml` se contente
  d'appeler `uv run python scripts/gold_dataset_sync.py` puis
  `uv run python scripts/gold_dataset_eval.py`, et redirige un résumé vers
  `$GITHUB_STEP_SUMMARY` — toute la logique métier reste testable/exécutable
  en local sans CI.
- **API exacte du SDK Langfuse (Datasets/Experiments) vérifiée à
  l'implémentation (Task 3-4), pas devinée** — même principe déjà appliqué
  pour le tracing (`tasks/plan-langfuse-tracing.md`). Point d'attention
  particulier : la méthode d'upsert d'un item de dataset par id stable
  (créer vs mettre à jour), et la forme exacte des `Evaluation` retournées
  par les évaluateurs `run_experiment`.

## Dependency Graph

```
Task 0: Résoudre document_id 9 (PDF manquant) — bloquant, utilisateur
    │
    ▼
Task 1: Committer les 14 PDF gold (retrait .gitignore)   Task 2: Fixture champs gold (CSV) + seeding DB jetable
    │                                                          │
    └──────────────────────────┬───────────────────────────────┘
                                ▼
                    Task 3: scripts/gold_dataset_sync.py (YAML -> Dataset Langfuse)
                                │
                                ▼
                    Task 4: scripts/gold_dataset_eval.py — task callable (pipeline réel)
                                + run_experiment sans évaluateurs
                                │
                                ▼
                    Task 5: Évaluateurs item-level (scripts/gold_matching.py + wiring)
                                │
                                ▼
                    Task 6: Évaluateurs run-level (agrégats, bucket human_validation)
                                │
                                ▼
                    Task 7: Workflow GitHub Actions (workflow_dispatch) + step summary
                                │
                                ▼
                    Task 8: Vérification manuelle bout-en-bout + housekeeping
```

**Parallélisable** : Task 1 et Task 2 n'ont pas de dépendance entre elles
(l'une committe des PDF, l'autre écrit un CSV + du code de seeding) — les
deux dépendent seulement de Task 0.

**Séquentiel obligatoire** : tout le reste — chaque script dépend du
précédent pour avoir quelque chose de réel à envelopper (pas de valeur à
paralléliser vu la taille du scope).

## Task List

### Phase 0: Intégrité des données (bloquant)
- [ ] Task 0: Résoudre `document_id: 9` (PDF manquant dans `data_test/`)

### Checkpoint: Intégrité des données
- [ ] Les 14 `source_file` du YAML existent tous dans `data_test/`
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 1: Fondations (parallélisables)
- [ ] Task 1: Committer les 14 PDF gold (retrait `data_test/` du `.gitignore`)
- [ ] Task 2: Fixture `tests/data/gold_devis_fields.csv` + seeding DB jetable

### Checkpoint: Fondations
- [ ] `git show HEAD --stat` liste bien les 14 PDF
- [ ] Un script ad hoc seedant une DB jetable depuis le CSV produit 6 `Field`
      valides (id, key, title, definition, type)
- [ ] `uv run pytest -v -m "not live"` passe, aucune régression
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 2: Sync + pipeline réel
- [ ] Task 3: `scripts/gold_dataset_sync.py`
- [ ] Task 4: `scripts/gold_dataset_eval.py` — task callable + `run_experiment` sans évaluateurs

### Checkpoint: Pipeline branché
- [ ] `uv run python scripts/gold_dataset_sync.py` crée/actualise le Dataset
      Langfuse `gold-devis` avec 14 items
- [ ] `uv run python scripts/gold_dataset_eval.py` produit un Dataset Run
      visible dans l'UI Langfuse (sans score pour l'instant)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 3: Métriques
- [ ] Task 5: Évaluateurs item-level (`scripts/gold_matching.py` + wiring)
- [ ] Task 6: Évaluateurs run-level (agrégats macro/micro, bucket `human_validation`)

### Checkpoint: Métriques
- [ ] `uv run pytest -v tests/test_gold_matching.py tests/test_gold_dataset_eval.py` passe
- [ ] Un run réel affiche, dans l'UI Langfuse, les scores item-level et
      run-level attendus (précision/recall/F1, coût, latence, split OCR)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 4: CI + vérification
- [ ] Task 7: Workflow GitHub Actions (`workflow_dispatch`) + step summary
- [ ] Task 8: Vérification manuelle bout-en-bout + housekeeping

### Checkpoint: Complete
- [ ] Tous les success criteria de `specs/ci-eval-gold-dataset.md` sont cochés
- [ ] Deux runs successifs du workflow sont comparables dans l'UI Langfuse
- [ ] Revue finale avec l'utilisateur

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `document_id: 9` reste sans PDF | High (bloque Task 1 et tout le reste) | Task 0 explicitement bloquante en première position ; le reste du plan ne démarre pas tant qu'elle n'est pas résolue. |
| API exacte d'upsert d'un item de Dataset Langfuse par id stable inconnue à ce stade | Medium | Vérifier la doc/le SDK à Task 3 (skill `langfuse`, principe "Documentation First") avant de coder ; si l'upsert par id n'existe pas nativement, fallback : lister les items existants et faire l'upsert "à la main" (delete+create) — décision à documenter dans le fichier une fois vérifiée. |
| Coût Gemini réel à chaque exécution manuelle des scripts pendant le développement (Tasks 4-6 nécessitent des runs réels pour vérifier le câblage) | Low-Medium | Développer/tester les évaluateurs (Task 5-6) sur des résultats simulés (`tests/test_gold_dataset_eval.py`, pas de réseau) ; ne lancer le script complet contre le vrai pipeline qu'aux checkpoints, pas à chaque itération de code. |
| Convention TP/FP/FN "valeur erronée = 1 FP + 1 FN" mal comprise si un futur relecteur s'attend à une convention de classification classique | Low | Documentée explicitement dans les Architecture Decisions ci-dessus et reprise en commentaire dans `scripts/gold_matching.py` à l'implémentation. |
| Exclusion `human_validation: false` implémentée par filtrage de la sync plutôt que par agrégation, cassant la traçabilité complète voulue | Low | Tranché ci-dessus (Architecture Decisions) : sync inclut tout, l'agrégation fait la distinction — à respecter à Task 6. |
| Taille des PDF committés (Task 1) plus importante que prévu, ralentissant les clones/CI | Low | Vérifier la taille totale exacte avant commit (Task 1) ; alternative Git LFS déjà écartée en idéation mais réévaluable si le total dépasse quelques dizaines de Mo. |

## Open Questions

Aucune bloquante restante pour démarrer, hormis Task 0 (voir Risks). Un point
à trancher pendant l'implémentation, pas avant :
- Deux Datasets Langfuse séparés (validés/non-validés) vs un seul avec
  filtrage par métadonnée pour la distinction `human_validation` — dépend de
  ce que l'API `run_experiment` permet facilement une fois vérifiée (Task 6).
