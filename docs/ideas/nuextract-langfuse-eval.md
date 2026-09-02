# Pipeline NuExtract sur Langfuse (comparaison multi-modèles)

## Problem Statement

Comment brancher le pipeline NuExtract sur le Dataset Langfuse `gold-devis`
existant, en réutilisant le scoring déjà générique de `gold_dataset_eval.py`,
pour comparer plusieurs pipelines/modèles côte à côte dans le dashboard
Langfuse Cloud — sans dupliquer la logique de scoring ni garder un chemin
CSV parallèle ?

## Recommended Direction

Nouveau script `scripts/nuextract_gold_langfuse_eval.py`, calqué sur
`run_eval()`/`main()` de `scripts/gold_dataset_eval.py` :

- Un `task` NuExtract-only (appelle `nuextract_client.extract`, mesure
  `latency_seconds`) — pas d'`ocr_page_count` (champ absent/0, ce pipeline
  n'OCRise rien).
- Réutilise **tel quel**, importé depuis `gold_dataset_eval.py` :
  `build_field_evaluator`/`build_run_evaluator` — même TP/FP/FN, P/R/F1,
  `grounding_accuracy` (toujours ignoré, pas de grounding v1),
  `latency_p50/p95`. Ces deux fonctions ne référencent rien de spécifique à
  LangExtract, elles lisent uniquement `output["extraction_results"]`.
- `dataset.run_experiment(name=f"gold-devis-nuextract-{model}-{date.today()}", ...)`
  sur le Dataset `gold-devis` existant — un run par jour/modèle, jamais
  écrasé, comparable dans la vue "Dataset Runs" à `gold-devis-eval`
  (LangExtract).
- `cost_usd_total` **calculé**, pas figé à `0.0` comme pour LangExtract :
  somme des `latency_seconds` de chaque item / 3600 × `0.80` (tarif GPU L4
  Modal, constante en dur dans le script). Approximation qui **surestime**
  sous concurrence (les items concurrents se chevauchent en horloge murale,
  cette somme les traite comme séquentiels) — mais bien plus utile qu'un
  `0.0` silencieux, cohérent avec le principe "reporting seul" déjà en
  place pour LangExtract.
- `max_concurrency=14` (= nombre de documents gold, tous en une vague) —
  vLLM bat les requêtes concurrentes en interne (continuous batching), donc
  pousser la concurrence accélère le run sans multiplier le coût GPU réel
  (le conteneur Modal reste unique, `max_containers=1`).
- Suppression de `scripts/nuextract_pipeline_eval.py` et
  `tests/test_nuextract_pipeline_eval.py` (chemin CSV) une fois le script
  Langfuse fonctionnel — un seul chemin d'éval à maintenir.

## Key Assumptions to Validate

- [ ] Deux `run_experiment(name=...)` avec des noms différents (même
      dataset) apparaissent bien comme deux runs distincts et comparables
      dans l'UI Langfuse "Dataset Runs" — à vérifier contre la doc/le SDK
      avant de coder (skill `langfuse`, principe "Documentation First" déjà
      appliqué dans ce repo pour `gold_dataset_sync.py`).
- [ ] `max_concurrency=14` ne sature pas le serveur Modal (`max_containers=1`)
      au point de dégrader la latence par item plus qu'il n'accélère le run
      global — à observer sur le premier run réel (fait par l'humain).
- [ ] `nuextract_client.extract` supporte d'être appelé en concurrence
      (plusieurs tasks Langfuse simultanées) sans état partagé problématique
      — le client `openai` est stateless par appel, a priori oui, pas de
      test de concurrence existant pour le confirmer.
- [ ] Le tarif `0.80 €/h` reste stable (GPU L4, région Modal actuelle) — sinon
      `cost_usd_total` dérive silencieusement jusqu'à la prochaine mise à
      jour manuelle de la constante.

## MVP Scope

**In :**
- `scripts/nuextract_gold_langfuse_eval.py` : task NuExtract +
  `dataset.run_experiment` réutilisant les évaluateurs existants, nom de run
  `gold-devis-nuextract-{model}-{date}`, `cost_usd_total` calculé,
  `max_concurrency=14`.
- Suppression de `scripts/nuextract_pipeline_eval.py` +
  `tests/test_nuextract_pipeline_eval.py`.
- Tests offline (mock du client NuExtract + du dataset Langfuse) pour le
  nouveau `task`.

**Out :** modification de `gold_dataset_eval.py` (LangExtract) ; grounding
précis ; run réel sur le gold (reste à l'humain, règle CLAUDE.md).

## Not Doing (and Why)

- **Retrofit du nommage `gold-devis-eval` (LangExtract) en
  pipeline+modèle+date** — cohérent à terme, mais hors scope : touche un
  fichier qui marche déjà, et le besoin immédiat est la comparaison
  NuExtract, pas une refonte du script existant.
- **Cost tracking exact (temps d'horloge murale du run plutôt que somme des
  latences item)** — demanderait de mesurer le temps autour de
  `run_experiment()` et de pousser le score après coup (les
  `run_evaluators` s'exécutent avant que l'appelant récupère le résultat) —
  complexité non justifiée pour un chiffre déjà utile en approximation
  (majorante, jamais optimiste).
- **`--tag` libre en plus de la date** — nom = pipeline+modèle+date seul
  (décidé) ; deux runs le même jour porteront le même nom — accepté comme
  compromis.
- **Garder le CSV en parallèle** — supprimé, un seul chemin d'éval (décidé).

## Open Questions

Aucune bloquante restante — toutes tranchées par les réponses ci-dessus.
