# Plan: Éval Langfuse NuExtract sur le dataset train + evidence

## Overview

Étendre le pipeline d'éval Langfuse existant (aujourd'hui limité au corpus
gold, 14 documents) à un second corpus, "train" (34 documents, 3 fichiers
YAML `tests/data/train/web_documents_2026-09-0{2,3,4}.yaml`), en réutilisant
au maximum le code déjà écrit pour le gold (`scripts/gold_dataset_eval.py`,
`scripts/gold_dataset_sync.py`, `scripts/nuextract_gold_langfuse_eval.py`)
sans y toucher. En parallèle, le schéma d'extraction NuExtract
(`scripts/nuextract_client.py`) passe d'un template plat par champ
(`{field.key: "verbatim-string"}`) à un template imbriqué
(`{field.key: {"value": "verbatim-string", "evidence": "verbatim-string"}}`),
pour que le pipeline produise aussi une citation verbatim justifiant chaque
valeur — utile immédiatement pour une nouvelle métrique Langfuse
(`evidence_similarity`, score continu, comparée à `evidence.text` du gold/train
via similarité de texte) et, plus tard (hors scope ici), comme signal pour
l'optimisation de prompt GEPA (DSPy).

Contexte déjà vérifié en amont (`/interview-me`), pas à re-vérifier :
`data_test/train/` contient exactement 34 PDF, les 3 YAML référencent
exactement ces 34 `source_file` (l'entrée orpheline
`BATIMONTAGE_devis_2021176-BLCREA.pdf` a été retirée par l'utilisateur),
les `document_id` sont uniques par fichier YAML mais pas entre les 3
fichiers, les 6 clés de champs sont identiques à celles du gold (réutiliser
`load_gold_fields()`), tous les documents ont `human_validation: true`, et
les PDF train vivent dans `data_test/train/` (pas `data_test/` comme pour
le gold).

## Architecture Decisions

- **Schéma NuExtract imbriqué plutôt que deux appels séparés** : un seul
  appel modèle par fenêtre continue de produire value+evidence ensemble
  (`{key: {value, evidence}}`), pas un second appel dédié à l'evidence —
  NuExtract supporte les objets JSON imbriqués (confirmé sur le README à
  jour du repo `numindai/nuextract`, le pattern `{value,evidence}` précis
  n'y est pas montré explicitement mais n'est pas un type spécial, c'est un
  objet générique comme `line_items`).
- **`ExtractionResult.evidence` optionnel (`str | None = None`)** plutôt
  qu'un nouveau modèle : tous les autres extracteurs (`LangExtractNerExtractor`,
  `mock_ner`) continuent de fonctionner sans le renseigner ; la persistance
  DB (`app/extraction_repository.py`) fait déjà une sélection de colonnes
  explicite (whitelist), donc ce champ supplémentaire ne touche ni le
  schéma SQLite ni aucune requête existante — confirmé par lecture du code,
  aucune migration nécessaire.
- **`train_dataset_sync.py` fusionne 3 YAML en un seul Dataset Langfuse**
  `"train-devis"` — id d'item `f"{DATASET_NAME}-{yaml_stem}-{document_id}"`
  (ex: `train-devis-web_documents_2026-09-02-20`) pour rester globalement
  unique (contrainte documentée dans `gold_dataset_sync.py` :
  `create_dataset_item` upsert par id, l'id doit être unique au-delà du
  dataset) malgré les `document_id` qui se chevauchent entre fichiers YAML.
- **`nuextract_train_langfuse_eval.py` réutilise `build_task` de
  `nuextract_gold_langfuse_eval.py` tel quel** (déjà paramétré par
  `data_test_dir`), au lieu d'en réécrire un — seul `data_test_dir` change
  (`data_test/train` au lieu de `data_test`). Idem pour tous les helpers de
  scoring (`_field_metrics_evaluations`, `_exact_match_accuracy`,
  `_grounding_accuracy`, `_latency_evaluations`, `_percentile`,
  `build_field_evaluator`, `load_gold_fields`, `_extraction_latency_evaluations`,
  `_cost_evaluation`) : importés, jamais copiés ni modifiés — mêmes
  imports "privés" que `nuextract_gold_langfuse_eval.py` fait déjà depuis
  `gold_dataset_eval.py` (convention déjà établie dans ce repo).
- **`evidence_similarity` est un évaluateur Langfuse séparé**, ajouté à la
  liste `evaluators=[...]` de `dataset.run_experiment` en plus de
  `build_field_evaluator` (importé, inchangé) — pas de fork de
  `build_field_evaluator` pour y injecter l'evidence. `dataset.run_experiment`
  accepte une liste d'évaluateurs item-level, chacun retournant sa propre
  liste d'`Evaluation` ; Langfuse les fusionne par item. Un second évaluateur
  run-level dédié (`_evidence_similarity_evaluations`) agrège ces scores.
- **Score continu, pas de seuil binaire** : `difflib.SequenceMatcher(None,
  gold_normalisé, extrait_normalisé).ratio()` (0.0-1.0), texte normalisé via
  `scripts.gold_matching._normalize_text` (casefold + espaces collapsés,
  déjà utilisé pour la comparaison de `value`, réutilisé tel quel). Score
  non calculé (champ absent de l'agrégat, pas 0.0) quand le gold n'a pas
  d'`evidence.text` — rien à comparer. Score `0.0` quand le gold a une
  evidence mais que l'extraction n'en produit aucune — un vrai manque.
- **Page ignorée pour cette métrique** (confirmé par l'utilisateur) — la
  métrique `grounding_accuracy` existante (page de la `value`) reste
  inchangée et continue de mesurer autre chose.

## Task List

### Phase 1: Schéma d'extraction NuExtract (evidence)

- [ ] Task 1: `ExtractionResult.evidence` — nouveau champ optionnel
- [ ] Task 2: Template NuExtract imbriqué `{value, evidence}` + parsing

### Checkpoint: Phase 1
- [ ] `uv run pytest tests/test_models.py tests/test_nuextract_client.py -v` passe
- [ ] Aucune régression sur les autres suites touchant `ExtractionResult`
      (`tests/test_extraction_routes.py tests/test_extraction_repository.py
      tests/test_dspy_prompt_tuning.py`)

### Phase 2: Dataset train unifié + éval de base (parité gold)

- [ ] Task 3: `train_dataset_sync.py` — fusion des 3 YAML en un Dataset
      Langfuse `"train-devis"`
- [ ] Task 4: `nuextract_train_langfuse_eval.py` — run de base (mêmes
      métriques que le gold, sans `evidence_similarity`)

### Checkpoint: Phase 2
- [ ] `uv run pytest tests/test_train_dataset_sync.py
      tests/test_nuextract_train_langfuse_eval.py -v` passe (offline, aucun
      appel réseau réel)
- [ ] Revue rapide avec l'utilisateur avant Phase 3 si un doute subsiste sur
      le découpage id/dataset

### Phase 3: Métrique evidence_similarity + run réel

- [ ] Task 5: `evidence_similarity` — évaluateur item-level + agrégation
      run-level
- [ ] Task 6: Exécution réelle du sync + du run contre le vrai serveur
      NuExtract (Modal), vérification dans l'UI Langfuse

### Checkpoint: Complete
- [ ] Toute la suite de tests passe : `uv run pytest -v`
- [ ] Run `"train-devis"` visible dans Langfuse avec les métriques attendues
      (P/R/F1 par champ + macro/micro, `exact_match_accuracy`,
      `grounding_accuracy`, latence p50/p95, coût, `evidence_similarity:*`,
      `evidence_similarity_macro`)
- [ ] Prêt pour revue (`/code-review-and-quality`) puis proposition de PR

## Suivi : concurrence client (branche feat/nuextract-async-concurrency)

Diagnostic + fix documentés dans le plan de session
(`asyncio.to_thread` dans `build_task`, voir commit "fix(nuextract):
vraie concurrence client via asyncio.to_thread"). Vérifié en réel sur un
second run `train-devis` : temps mur total du run 22 min -> 9m11s (~2,4x),
qualité inchangée (`f1_macro` 0.640 -> 0.645, `evidence_similarity_macro`
0.763 -> 0.764). Effet de bord repéré, pas corrigé : `cost_usd_total`
grimpe artificiellement (0.295€ -> 0.626€) car sa formule somme les
latences comme si elles étaient séquentielles (biais déjà documenté dans
le code, juste invisible tant que l'exécution était accidentellement
séquentielle) -- candidat de tâche séparée si un coût fiable est
nécessaire.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Le template imbriqué dégrade la qualité d'extraction de `value` (modèle non testé sur ce pattern précis) | Medium | Comparer les métriques `f1_macro`/`exact_match_accuracy` du run train avec les runs gold existants après Task 6 ; si régression nette, envisager de revenir au schéma plat pour `value` et de garder `evidence` optionnel côté client uniquement (discussion à ouvrir avec l'utilisateur, pas une décision à prendre seul) |
| Un document du dataset train fait échouer `extract()` (cold-start épuisé, page illisible) pendant le run réel (Task 6) | Low | Comportement déjà géré par `_create_completion_with_retries` (retry existant, inchangé) ; si un item échoue malgré tout, `dataset.run_experiment` continue les autres items (comportement déjà observé sur le gold) |
| Confusion entre les deux jeux de métriques `grounding_accuracy` (page) et `evidence_similarity` (texte) en lecture du run Langfuse | Low | Noms de métriques distincts + docstring explicite dans le nouvel évaluateur |

## Open Questions

Aucune — intent confirmé en `/interview-me`, restate validé par l'utilisateur.
