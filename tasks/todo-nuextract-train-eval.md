# Tasks: Éval Langfuse NuExtract sur le dataset train + evidence

Plan : [tasks/plan-nuextract-train-eval.md](plan-nuextract-train-eval.md).

## Task 1: `ExtractionResult.evidence` — nouveau champ optionnel

**Description:** Ajouter `evidence: str | None = None` à `ExtractionResult`
(`app/models.py`), juste après `value` — texte verbatim justifiant `value`,
peuplé uniquement par `nuextract_client.extract` (Task 2), `None` pour tous
les autres extracteurs (`LangExtractNerExtractor`, `mock_ner`). Vérifié :
`app/extraction_repository.py` fait une sélection de colonnes explicite
(pas de `SELECT *`/`INSERT` dynamique), donc ce champ n'a besoin d'aucune
migration ni colonne SQLite — il n'est simplement pas persisté.

**Acceptance criteria:**
- [ ] `ExtractionResult(field_title="x", value="y")` reste valide,
      `.evidence is None`.
- [ ] `ExtractionResult(field_title="x", value="y", evidence="z")` valide,
      `.evidence == "z"`.
- [ ] Aucune autre classe/table modifiée.

**Verification:**
- [x] `uv run pytest tests/test_models.py -v`
- [x] `uv run pytest tests/test_extraction_repository.py
      tests/test_extraction_routes.py tests/test_dspy_prompt_tuning.py
      tests/test_ner_langextract_tracing.py -v` (non-régression, aucun de
      ces fichiers ne doit changer)

**Dependencies:** None

**Files likely touched:**
- `app/models.py`
- `tests/test_models.py`

**Estimated scope:** XS

---

## Task 2: Template NuExtract imbriqué `{value, evidence}` + parsing

**Description:** Dans `scripts/nuextract_client.py` :
- `build_template(fields)` renvoie
  `{field.key: {"value": "verbatim-string", "evidence": "verbatim-string"}}`
  par champ (au lieu de `{field.key: "verbatim-string"}`).
- `parse_response(content, fields)` : `parsed.get(field.key)` est maintenant
  un dict `{"value": ..., "evidence": ...}` (potentiellement absent/`None`
  si le modèle ne renvoie rien pour ce champ — garder le même filet de
  sécurité qu'aujourd'hui, ne pas lever si `raw` n'est pas un dict). En
  extraire `value` (coercion de type inchangée, via `type_coercion.validate`
  sur `value` uniquement — l'evidence n'est jamais typée) et `evidence`
  (texte brut, `None` si absent/vide plutôt que chaîne vide, pour
  distinguer "pas d'evidence" de "evidence vide" côté métrique Task 5).
- `_merge_window_results` : aucun changement de code nécessaire (fusionne
  déjà l'objet `ExtractionResult` entier par champ, `evidence` suit
  automatiquement) — à confirmer par un test dédié (fenêtre 2 avec value+
  evidence gagne sur fenêtre 1 vide).

**Acceptance criteria:**
- [ ] `build_template` renvoie le schéma imbriqué pour chaque champ.
- [ ] `parse_response` peuple `.value`/`.typed_value`/`.type_error` comme
      avant (aucune régression de comportement sur la coercion), et peuple
      `.evidence` depuis la sous-clé `"evidence"`.
- [ ] Un champ absent du JSON, ou dont la sous-valeur `"value"` est vide,
      produit toujours `value=""` (même convention qu'avant) et
      `evidence=None`.
- [ ] `extract()` transmet bien le nouveau template imbriqué au serveur
      (`chat_template_kwargs`) et le résultat final porte `.evidence`.

**Verification:**
- [x] `uv run pytest tests/test_nuextract_client.py -v` — mettre à jour :
      `test_build_template_maps_every_field_to_verbatim_string` (nouveau
      schéma attendu), `test_parse_response_maps_present_fields_with_type_coercion`,
      `test_parse_response_flags_a_value_that_does_not_coerce_to_the_field_type`,
      `test_parse_response_produces_an_empty_row_for_a_missing_or_blank_field`
      (contenu JSON imbriqué en entrée), `test_extract_sends_one_image_per_page_and_the_verbatim_string_template`
      (assertion sur le template imbriqué) — plus un nouveau test
      `test_parse_response_extracts_the_evidence_alongside_the_value`.

**Dependencies:** Task 1

**Files likely touched:**
- `scripts/nuextract_client.py`
- `tests/test_nuextract_client.py`

**Estimated scope:** M

---

## Checkpoint: Phase 1 (après Task 1-2)

- [x] `uv run pytest tests/test_models.py tests/test_nuextract_client.py -v`
- [x] `uv run pytest tests/test_extraction_routes.py
      tests/test_extraction_repository.py tests/test_dspy_prompt_tuning.py -v`
      (non-régression) — a aussi nécessité une mise à jour de
      `tests/test_nuextract_gold_langfuse_eval.py` (assertion stricte sur
      `model_dump()`, non prévue dans le plan initial mais dans le même
      esprit : fixture de test, pas le script de prod)
- [x] Revue rapide : le schéma imbriqué est bien celui discuté, aucun appel
      réseau réel effectué à ce stade ; suite complète `uv run pytest -q`
      -> 309 passed

---

## Task 3: `train_dataset_sync.py` — fusion des 3 YAML en un Dataset Langfuse

**Description:** Nouveau `scripts/train_dataset_sync.py`, calqué sur
`scripts/gold_dataset_sync.py` :
- `DATASET_NAME = "train-devis"`.
- `TRAIN_YAML_DIR = .../tests/data/train` ; charge tous les
  `web_documents_*.yaml` de ce dossier, triés par nom (déterministe).
- Un item Langfuse par document, tous fichiers confondus, id
  `f"{DATASET_NAME}-{yaml_path.stem}-{document_id}"` (unique même si un
  `document_id` se répète entre deux fichiers YAML — vérifié en amont que
  ce chevauchement existe réellement, voir plan).
- Même forme `input`/`expected_output`/`metadata` que
  `sync_gold_dataset` (`source_file`, `field_keys` triés,
  `doc["annotations"]`, `{document_id, human_validation}`).
- `sync_train_dataset(client, yaml_dir=TRAIN_YAML_DIR) -> int` retourne le
  nombre total de documents synchronisés (34 attendus aujourd'hui).

**Acceptance criteria:**
- [ ] `create_dataset(name="train-devis", ...)` appelé une fois.
- [ ] Un item par document des 3 YAML (34 au total sur les fichiers réels),
      aucun doublon même si deux fichiers partagent un `document_id`.
- [ ] Item `input`/`expected_output`/`metadata` fidèles au document source.
- [ ] Ré-exécuter la sync deux fois ne duplique rien (même id -> upsert).

**Verification:**
- [x] `uv run pytest tests/test_train_dataset_sync.py -v` (nouveau fichier,
      calqué sur `tests/test_gold_dataset_sync.py` : `_FakeLangfuseClient`
      réutilisable telle quelle par copie du même faux client minimal,
      fixtures YAML écrites dans `tmp_path` avec plusieurs fichiers et un
      `document_id` volontairement dupliqué entre deux d'entre eux pour
      couvrir la collision).

**Dependencies:** None (indépendant de Task 1-2, peut être fait en
parallèle)

**Files likely touched:**
- `scripts/train_dataset_sync.py`
- `tests/test_train_dataset_sync.py`

**Estimated scope:** S

---

## Task 4: `nuextract_train_langfuse_eval.py` — run de base (parité gold)

**Description:** Nouveau `scripts/nuextract_train_langfuse_eval.py`,
réutilisant par import (aucune copie) :
- `build_task` de `scripts/nuextract_gold_langfuse_eval.py`, appelé avec
  `data_test_dir=Path(__file__).resolve().parent.parent / "data_test" / "train"`.
- `build_field_evaluator`, `load_gold_fields`, `_field_metrics_evaluations`,
  `_exact_match_accuracy`, `_grounding_accuracy`, `_latency_evaluations`,
  `_percentile` de `scripts/gold_dataset_eval.py`.
- `_extraction_latency_evaluations`, `_cost_evaluation`,
  `_item_evaluation_value` de `scripts/nuextract_gold_langfuse_eval.py`.
- `run_eval(client=None, *, max_concurrency=14, model=nuextract_client._DEFAULT_MODEL)`
  résout `client.get_dataset("train-devis")` (synchronisé au préalable par
  Task 3), lance `dataset.run_experiment(name=f"train-devis-nuextract-{model}",
  task=build_task(...), evaluators=[build_field_evaluator(...)],
  run_evaluators=[build_run_evaluator()], max_concurrency=max_concurrency)`.
  Un `main()` avec `load_env()` + `print(result.format())`, comme les deux
  scripts d'éval existants.
- `build_run_evaluator()` propre à ce fichier (mêmes évaluations que celui
  du gold : `documents_evaluated`, `documents_excluded_unvalidated`,
  `_field_metrics_evaluations`, `_exact_match_accuracy`,
  `_grounding_accuracy`, `_latency_evaluations`,
  `_extraction_latency_evaluations`, `_cost_evaluation`) — **sans**
  `evidence_similarity` à ce stade (Task 5).

**Acceptance criteria:**
- [ ] `task()` lit le PDF depuis `data_test/train/`, pas `data_test/`.
- [ ] `run_eval` avec un extracteur factice (pas de réseau) produit les
      mêmes noms de métriques que le run gold existant, sur les items du
      dataset `"train-devis"`.
- [ ] Aucune ligne de `gold_dataset_eval.py` /
      `nuextract_gold_langfuse_eval.py` modifiée (diff vide sur ces deux
      fichiers).

**Verification:**
- [x] `uv run pytest tests/test_nuextract_train_langfuse_eval.py -v`
      (nouveau fichier, calqué sur
      `tests/test_nuextract_gold_langfuse_eval.py` : extracteur factice
      injecté, dataset/items simulés via le même style de faux client que
      Task 3, aucun appel réseau réel).

**Dependencies:** Task 2 (le faux extracteur de test doit pouvoir retourner
un `ExtractionResult` avec `evidence`, même si ce champ n'est pas encore
exploité par cette task), Task 3 (le run lit le dataset supposé synchronisé)

**Files likely touched:**
- `scripts/nuextract_train_langfuse_eval.py`
- `tests/test_nuextract_train_langfuse_eval.py`

**Estimated scope:** M

---

## Checkpoint: Phase 2 (après Task 3-4)

- [x] `uv run pytest tests/test_train_dataset_sync.py
      tests/test_nuextract_train_langfuse_eval.py -v`
- [x] `uv run pytest -v` (suite complète, aucune régression ailleurs) ->
      322 passed
- [x] Aucun appel réseau réel effectué jusqu'ici (ni Langfuse, ni Modal)

---

## Task 5: `evidence_similarity` — évaluateur item-level + agrégation run-level

**Description:** Dans `scripts/nuextract_train_langfuse_eval.py` :
- `build_evidence_similarity_evaluator(fields_by_key)` : évaluateur
  item-level supplémentaire (signature `(*, output, expected_output,
  metadata, **kwargs) -> list[Evaluation]`, même contrat que
  `build_field_evaluator`). Pour chaque `field_key` de `expected_output` :
  `gold_text = annotation.get("evidence", {}).get("text")` ;
  `extracted_text = output_by_key.get(field_key, {}).get("evidence")`. Si
  `gold_text` absent/vide : rien émis pour ce champ (pas de valeur à
  comparer). Si `gold_text` présent et `extracted_text` absent/vide :
  `Evaluation(name=f"evidence_similarity:{field_key}", value=0.0)`. Si les
  deux présents :
  `SequenceMatcher(None, _normalize_text(gold_text), _normalize_text(extracted_text)).ratio()`
  (`_normalize_text` importé de `scripts.gold_matching`, inchangé).
- `_evidence_similarity_evaluations(item_results)` : run-level, agrège les
  `evidence_similarity:{field_key}` par champ (moyenne simple, pas de
  pooling TP/FP/FN — ce n'est pas une classification) +
  `evidence_similarity_macro` (moyenne des moyennes par champ, même
  convention que `f1_macro`).
- Câblés dans `run_eval` : `evaluators=[build_field_evaluator(...),
  build_evidence_similarity_evaluator(...)]`, `build_run_evaluator`
  étendu avec `_evidence_similarity_evaluations(validated)`.

**Acceptance criteria:**
- [ ] Score `1.0` quand gold et evidence prédite sont identiques après
      normalisation (casefold + espaces).
- [ ] Score entre 0 et 1 (exclus les extrêmes) pour une evidence partiellement
      correcte (ex: bonne phrase mais tronquée).
- [ ] Champ absent de l'agrégat run-level quand aucun document n'a de
      `evidence.text` gold pour ce champ (pas de `0.0` trompeur).
- [ ] `evidence_similarity_macro` présent et cohérent (moyenne simple des
      moyennes par champ observées).

**Verification:**
- [x] `uv run pytest tests/test_nuextract_train_langfuse_eval.py -v -k evidence`
      (cas : match parfait, match partiel, gold sans evidence, extraction
      sans evidence alors que le gold en a une).

**Dependencies:** Task 4

**Files likely touched:**
- `scripts/nuextract_train_langfuse_eval.py`
- `tests/test_nuextract_train_langfuse_eval.py`

**Estimated scope:** M

---

## Task 6: Exécution réelle (sync + run) et vérification dans Langfuse

**Description:** Claude exécute (autorisation explicite de l'utilisateur,
qui ne s'applique qu'au dataset train, pas au gold) :
`uv run python scripts/train_dataset_sync.py` puis
`uv run python scripts/nuextract_train_langfuse_eval.py`, contre le vrai
serveur NuExtract (Modal) et le vrai projet Langfuse. Pas de nouveau code
dans cette task — uniquement l'exécution et la lecture du résultat.

**Acceptance criteria:**
- [ ] Dataset `"train-devis"` visible dans Langfuse avec 34 items.
- [ ] Un run `train-devis-nuextract-{model}` visible dans la vue "Dataset
      Runs", avec toutes les métriques attendues (voir Checkpoint: Complete
      du plan) et des valeurs plausibles (ex: `documents_evaluated == 34`,
      `evidence_similarity_macro` entre 0 et 1, pas d'exception levée sur
      un document).
- [ ] Comparaison qualitative rapide avec le run gold existant consignée
      (texte, pas de code) — sert de garde-fou pour le risque "schéma
      imbriqué dégrade `value`" du plan.

**Verification:**
- [x] Lien/URL du run Langfuse partagé avec l'utilisateur :
      https://cloud.langfuse.com/project/cmt1cflz104nvad0g35njubp0/datasets/cmtmxt4tf03k6ad0drn5up1jx/runs/52947633-b054-4435-9cb0-4f7ae6e73797
- [x] Pas de test automatisé (exécution réelle, pas de code produit). Sync
      a d'abord révélé 3 lignes YAML invalides (voir commit
      `fix(data): corrige la syntaxe YAML de 3 evidence.text (train)`),
      corrigées avant de relancer.

**Résultat réel (34 documents, tous `human_validation: true`) :**
`f1_macro: 0.640`, `precision_micro: 0.649`, `recall_micro: 0.715`,
`f1_micro: 0.681`, `exact_match_accuracy: 0.088`,
`grounding_accuracy: 0.000` (0/97 — NuExtract ne renseigne jamais
`page_number`, limitation connue du pipeline, pas une régression de ce
chantier), `evidence_similarity_macro: 0.763` (par champ : 0.602 à 0.886),
`latency_p50_seconds: 29.15`, `latency_p95_seconds: 97.9`,
`cost_usd_total: 0.295` (approximation documentée). Comparaison
qualitative : seule référence historique disponible est un run **LangExtract**
sur le gold (`tasks/todo-ci-eval-gold-dataset.md`, pipeline différent, 13
documents) : `f1_macro: 0.478`, `exact_match_accuracy: 0.077` — le F1 macro
NuExtract sur train est nettement meilleur, mais la comparaison reste
indicative (pipeline et dataset différents, pas un A/B strict). Champ le
plus faible : `delai_paiement_solde_jours` (`f1: 0.074`).

**Dependencies:** Task 1-5 (tout le code doit être en place et testé
offline avant ce run réel)

**Files likely touched:** aucun (exécution uniquement)

**Estimated scope:** XS

---

## Checkpoint: Complete

- [x] `uv run pytest -v` — suite complète verte (328 passed)
- [x] Run `"train-devis"` visible dans Langfuse avec toutes les métriques
      attendues, exécuté et vérifié (Task 6)
- [ ] Prêt pour `/code-review-and-quality`, puis proposition de PR (par
      règle CLAUDE.md, une fois la branche de feature complète)

## Suivi identifié pendant ce chantier (hors scope, pas traité ici)

Pendant l'attente du run réel, il est apparu que `dataset.run_experiment`
(Langfuse) exécute les items sur une seule boucle asyncio
(`asyncio.gather` + `asyncio.Semaphore(max_concurrency)`,
`langfuse/_client/client.py:2813`), et que `nuextract_client.py` utilise
`openai.OpenAI` (client **synchrone**) sans `run_in_executor`/
`asyncio.to_thread` -- chaque appel bloquant (HTTP + `time.sleep` de
retry) gèle donc toute la boucle, rendant les 34 documents quasi
**séquentiels côté client** malgré `max_concurrency=14`, et empêchant le
serveur vLLM (`--max-num-seqs 8`, continuous batching) de jamais recevoir
plus d'une requête à la fois. Affecte aussi `nuextract_gold_langfuse_eval.py`
(même pattern). Confirmé par l'utilisateur : à traiter dans une tâche de
planification séparée après ce chantier.
