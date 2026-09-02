# Tasks: Pipeline NuExtract sur Langfuse (comparaison multi-modèles)

Plan : [tasks/plan-nuextract-langfuse-eval.md](plan-nuextract-langfuse-eval.md).

## Task 1: Vérifier le comportement Langfuse pour des runs de noms distincts

**Description:** Avant d'écrire du code qui en dépend, confirmer que deux
appels `dataset.run_experiment(name=...)` avec des noms différents (même
dataset `gold-devis`) produisent bien deux runs distincts, listés
séparément et comparables dans la vue "Dataset Runs" de l'UI Langfuse —
pas de fusion/écrasement. Vérifier contre le SDK réellement installé
(`langfuse==4.14.5` ou version courante de `uv.lock`), même démarche que
`scripts/gold_dataset_sync.py` (skill `langfuse`, docstring du module).

**Acceptance criteria:**
- [ ] Comportement confirmé par lecture de la doc/du code source du SDK
      installé (pas une supposition).
- [ ] Une note courte (1-2 phrases) écrite, prête à être collée en
      docstring de `scripts/nuextract_gold_langfuse_eval.py` (Task 4),
      citant la source vérifiée.

**Verification:**
- [ ] Pas de test automatisé pour cette tâche (recherche, pas de code).

**Dependencies:** None

**Files likely touched:** aucun (recherche uniquement)

**Estimated scope:** XS

---

## Task 2: `build_task` — extraction NuExtract par item du dataset gold

**Description:** Créer `scripts/nuextract_gold_langfuse_eval.py` avec un
`build_task(fields_by_key, *, extractor=None, data_test_dir=DATA_TEST_DIR)`
qui retourne un callable `task(*, item, **kwargs)` : lit `item.input`
(`source_file`, `field_keys`), résout les `Field` réels, lit le PDF depuis
`data_test_dir`, appelle `extractor(pdf_bytes, fields)` (défaut
`nuextract_client.extract`, injectable pour les tests), mesure
`latency_seconds`, retourne
`{"extraction_results": [...], "latency_seconds": ...}` — même forme que
`gold_dataset_eval.build_task` mais sans étape PDF→texte séparée ni
`ocr_page_count` (ce pipeline n'OCRise rien).

**Acceptance criteria:**
- [ ] `task` lit le bon PDF, résout les bons champs, appelle `extractor`
      avec `(pdf_bytes, fields)`.
- [ ] `output["extraction_results"]` est une liste de dicts
      (`ExtractionResult.model_dump()`), compatible tel quel avec
      `build_field_evaluator` (importé, inchangé) de `gold_dataset_eval.py`.
- [ ] `output["latency_seconds"] >= 0`.

**Verification:**
- [ ] `uv run pytest -v tests/test_nuextract_gold_langfuse_eval.py -k build_task`
- [ ] Test avec un extracteur factice (mirror de
      `test_build_task_reads_the_referenced_pdf_and_extracts_selected_fields`
      dans `tests/test_gold_dataset_eval.py`) — pas d'appel réseau.

**Dependencies:** None (peut démarrer en parallèle de Task 1)

**Files likely touched:**
- `scripts/nuextract_gold_langfuse_eval.py` (nouveau)
- `tests/test_nuextract_gold_langfuse_eval.py` (nouveau)

**Estimated scope:** S

---

## Task 3: `build_run_evaluator` — coût réel + helpers réutilisés

**Description:** Dans le même fichier, ajouter une constante
`_GPU_COST_PER_HOUR = 0.80` (commentée : tarif GPU L4 Modal, voir
`docs/ideas/nuextract-langfuse-eval.md`), une fonction `_cost_evaluation`
(somme des `latency_seconds` des `item_results` / 3600 ×
`_GPU_COST_PER_HOUR`, `Evaluation(name="cost_usd_total", ...)` avec un
`comment` explicite sur l'approximation), et `build_run_evaluator()`
composé à partir de `_field_metrics_evaluations`, `_exact_match_accuracy`,
`_grounding_accuracy`, `_latency_evaluations`, `_item_evaluation_value`
**importés depuis `scripts/gold_dataset_eval.py`** (pas réimplémentés) —
filtrage `human_validation` identique à l'existant (le champ vient de
`build_field_evaluator`, réutilisé sans changement). Pas de
`_ocr_split_evaluations` (non pertinent, ce pipeline n'OCRise rien).

**Acceptance criteria:**
- [ ] Documents `human_validation: false` exclus des métriques
      principales, comptés à part — même comportement que
      `gold_dataset_eval.build_run_evaluator`.
- [ ] `cost_usd_total` = somme des latences / 3600 × 0.80, avec un
      `comment` qui explique l'approximation (majorant sous concurrence).
- [ ] P/R/F1 macro/micro, `exact_match_accuracy`, `grounding_accuracy`,
      `latency_p50/p95` présents et corrects (mêmes calculs que l'existant,
      juste réassemblés).
- [ ] Aucune `Evaluation` `documents_with_ocr`/`documents_without_ocr`
      dans la sortie.

**Verification:**
- [ ] `uv run pytest -v tests/test_nuextract_gold_langfuse_eval.py -k run_evaluator`
- [ ] Tests mirroring `test_run_evaluator_*` de
      `tests/test_gold_dataset_eval.py` (mêmes fixtures `_item_result`,
      réutilisables telles quelles ou copiées) + un test dédié pour le
      calcul de coût (latences connues → `cost_usd_total` attendu).
- [ ] `uv run pytest -v tests/test_gold_dataset_eval.py` — aucune
      régression (fichier non modifié, juste importé).

**Dependencies:** Task 2 (même fichier)

**Files likely touched:**
- `scripts/nuextract_gold_langfuse_eval.py`
- `tests/test_nuextract_gold_langfuse_eval.py`

**Estimated scope:** S

---

## Task 4: `run_eval()`/`main()` — nom de run, wiring complet

**Description:** Ajouter `_run_name(model: str) -> str` (fonction pure,
`f"gold-devis-nuextract-{model.replace('/', '_')}-{date.today().isoformat()}"`),
`run_eval(client=None, *, max_concurrency=14, model=None)` (résout
`fields_by_key` via `load_gold_fields()`, `dataset = client.get_dataset(DATASET_NAME)`
— `DATASET_NAME` importé de `gold_dataset_sync.py`, construit `task` via
`build_task`, appelle
`dataset.run_experiment(name=_run_name(model), task=task, evaluators=[build_field_evaluator(fields_by_key)], run_evaluators=[build_run_evaluator()], max_concurrency=max_concurrency)`),
et `main()` (`load_env()` + `run_eval()` + `print(result.format())`).
Inclure en tête de fichier la note de Task 1 (comportement Langfuse
vérifié).

**Acceptance criteria:**
- [ ] `_run_name("numind/NuExtract3")` ne contient pas de `/` et inclut la
      date du jour au format ISO.
- [ ] `run_eval` appelle `client.get_dataset("gold-devis")` puis
      `dataset.run_experiment` avec les bons `name`/`task`/`evaluators`/
      `run_evaluators`/`max_concurrency=14` par défaut.
- [ ] `main()` charge `.env` avant de lancer le run (comme
      `gold_dataset_eval.main`).

**Verification:**
- [ ] `uv run pytest -v tests/test_nuextract_gold_langfuse_eval.py -k "run_name or run_eval"`
- [ ] Test de `_run_name` (pure, pas de mock).
- [ ] Test de `run_eval` avec un client Langfuse factice (capture des
      kwargs passés à `run_experiment`, pas d'appel réseau réel).
- [ ] `uv run pytest -v -m "not live"` — suite complète, aucune régression.

**Dependencies:** Task 2, Task 3

**Files likely touched:**
- `scripts/nuextract_gold_langfuse_eval.py`
- `tests/test_nuextract_gold_langfuse_eval.py`

**Estimated scope:** S

---

## Task 5: Suppression du chemin CSV

**Description:** Une fois Task 4 vérifiée (tests offline verts), supprimer
`scripts/nuextract_pipeline_eval.py` et
`tests/test_nuextract_pipeline_eval.py` — décidé en cadrage : un seul
chemin d'éval NuExtract à maintenir (Langfuse), le CSV devient redondant.

**Acceptance criteria:**
- [ ] Les deux fichiers n'existent plus.
- [ ] Aucune référence résiduelle à `nuextract_pipeline_eval` ailleurs
      dans le repo (grep avant suppression).

**Verification:**
- [ ] `grep -rn "nuextract_pipeline_eval" --include="*.py" --include="*.md" .`
      ne renvoie rien après suppression.
- [ ] `uv run pytest -v -m "not live"` — suite complète toujours verte
      après suppression.

**Dependencies:** Task 4 (le nouveau script doit être fonctionnel et testé
avant de retirer l'ancien chemin)

**Files likely touched:**
- `scripts/nuextract_pipeline_eval.py` (supprimé)
- `tests/test_nuextract_pipeline_eval.py` (supprimé)

**Estimated scope:** XS

---

## Checkpoint final

- [ ] `uv run pytest -v -m "not live"` passe intégralement.
- [ ] Aucune modification de `app/`, `scripts/gold_dataset_eval.py`,
      `scripts/gold_dataset_sync.py`, `scripts/gold_matching.py` (tous
      seulement importés, jamais édités).
- [ ] `scripts/nuextract_gold_langfuse_eval.py` prêt pour un premier run
      réel — **fait par l'humain**, pas par Claude.
- [ ] Proposer `/code-review-and-quality` puis une PR pour l'ensemble du
      spike NuExtract (branche `feat/nuextract-pipeline-spike`).
