# Implementation Plan: Pipeline NuExtract sur Langfuse (comparaison multi-modèles)

Cadrage : [docs/ideas/nuextract-langfuse-eval.md](../docs/ideas/nuextract-langfuse-eval.md).
Branche : `feat/nuextract-pipeline-spike` (suite du spike NuExtract déjà en
cours sur cette branche, pas de nouvelle branche).

## Overview

Brancher le pipeline NuExtract (`scripts/nuextract_client.py`, déjà
fonctionnel et smoke-testé) sur le Dataset Langfuse `gold-devis` existant,
via un nouveau script `scripts/nuextract_gold_langfuse_eval.py`, en
réutilisant le scoring déjà pipeline-agnostique de `gold_dataset_eval.py`
(`build_field_evaluator` inchangé + helpers privés du run-evaluator
recomposés avec un calcul de coût réel). Le chemin CSV existant
(`scripts/nuextract_pipeline_eval.py`) est supprimé une fois le nouveau
script fonctionnel — un seul chemin d'éval à maintenir.

## Architecture Decisions

- **Nouveau fichier, pas de modification de `gold_dataset_eval.py`** —
  décidé en cadrage (idea-refine) : ce fichier est déjà testé/utilisé pour
  LangExtract, on ne le touche pas pour un second pipeline encore au stade
  spike.
- **`build_field_evaluator` importé et réutilisé tel quel** — ne référence
  que `output["extraction_results"]`, déjà pipeline-agnostique, aucune
  modification nécessaire.
- **`build_run_evaluator` en revanche N'EST PAS réutilisable tel quel** :
  il pose `cost_usd_total=0.0` en dur avec un commentaire spécifique à
  LangExtract ("LangExtract n'expose aucune info d'usage token"). Comme ce
  chantier veut un coût **calculé** pour NuExtract, le nouveau script
  compose sa propre fonction run-evaluator à partir des **helpers privés
  déjà existants et réutilisables tels quels** (`_field_metrics_evaluations`,
  `_exact_match_accuracy`, `_grounding_accuracy`, `_latency_evaluations`,
  `_item_evaluation_value`), importés directement depuis
  `gold_dataset_eval.py` — import de symboles préfixés `_` déjà pratiqué
  dans ce repo (`scripts/dspy_prompt_tuning.py` importe déjà `_api_key_for`/
  `_is_openai_model` depuis `app/tools/ner_langextract.py`), donc cohérent
  avec la convention existante plutôt qu'une exception.
- **`_ocr_split_evaluations` délibérément exclu** du nouveau run-evaluator —
  NuExtract n'OCRise rien, cette métrique n'aurait aucun sens (toujours
  `documents_with_ocr=0`).
- **`max_concurrency=14`** (= nombre de documents gold) — décidé en
  cadrage : vLLM bat les requêtes concurrentes en interne, un seul
  conteneur Modal suffit à les absorber sans coût GPU supplémentaire.
- **Nom de run** : `gold-devis-nuextract-{model}-{date}` (slash de
  `model` remplacé par `_` pour un nom d'URL-safe) — un run par jour/modèle,
  jamais écrasé (décidé en cadrage).
- **`cost_usd_total`** : somme des `latency_seconds` par item / 3600 ×
  `0.80` (constante en dur, tarif GPU L4 Modal — décidé en cadrage,
  approximation majorante sous concurrence, documentée dans le `comment`
  de l'`Evaluation`).

## Task List

### Phase 0 : Risque le plus élevé — vérifier avant de coder

- [ ] Task 1: Vérifier le comportement Langfuse pour des runs de noms
      distincts sur le même dataset

### Checkpoint : Phase 0
- [ ] Comportement confirmé (doc SDK ou lecture du code installé), noté en
      commentaire dans le futur `scripts/nuextract_gold_langfuse_eval.py`
      (même pratique que `gold_dataset_sync.py`, "Documentation First").

### Phase 1 : Foundation — task callable + run-evaluator

- [ ] Task 2: `build_task` — extraction NuExtract par item du dataset gold
- [ ] Task 3: `build_run_evaluator` — coût réel + helpers réutilisés

### Checkpoint : Phase 1
- [ ] `uv run pytest -v -m "not live"` passe, y compris les nouveaux tests
      offline.
- [ ] Aucune régression sur `tests/test_gold_dataset_eval.py` (les helpers
      importés ne sont pas modifiés, juste réutilisés).

### Phase 2 : Wiring + nettoyage

- [ ] Task 4: `run_eval()`/`main()` — nom de run, `dataset.run_experiment`,
      wiring complet
- [ ] Task 5: Suppression du chemin CSV
      (`scripts/nuextract_pipeline_eval.py` + son test)

### Checkpoint : Complete
- [ ] `uv run pytest -v -m "not live"` passe intégralement.
- [ ] `scripts/nuextract_gold_langfuse_eval.py` prêt pour un premier run
      réel — **fait par l'humain**, pas par Claude (règle CLAUDE.md, ce
      chantier n'est pas du DSPy).
- [ ] Review avec l'humain avant PR (le spike NuExtract complet, y compris
      ce chantier, sera proposé pour `/code-review-and-quality` puis PR).

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Deux runs de même préfixe mais dates différentes ne sont pas comparables comme attendu dans l'UI Langfuse | Medium — invalide la prémisse "comparer dans le temps" | Task 1 vérifie ça en premier, avant tout code dépendant |
| `max_concurrency=14` sature le conteneur Modal unique (`max_containers=1`) et dégrade la latence par item | Low — dégrade la vitesse du run, ne casse rien fonctionnellement | Observable au premier run réel (fait par l'humain) ; valeur ajustable, pas figée dans une API publique |
| Le tarif `0.80 €/h` devient obsolète (changement de GPU/région) | Low — `cost_usd_total` dérive silencieusement | Constante isolée en tête de fichier, commentée avec sa source, facile à corriger |

## Open Questions

Aucune bloquante — voir `docs/ideas/nuextract-langfuse-eval.md` pour
l'historique des décisions de cadrage.
