# Séparer cold-start et latence d'extraction (Langfuse)

## Problem Statement

Comment isoler, par document, le temps passé en attente de retry
(essentiellement le cold-start du serveur Modal) du vrai temps
d'extraction, dans le run Langfuse `gold-devis-nuextract-*`, pour que la
latence p50/p95 reflète l'inférence réelle plutôt qu'un artefact du
cold-start ?

## Recommended Direction

- `extract()` (`scripts/nuextract_client.py`) gagne un paramètre optionnel
  `on_retry: Callable[[float], None] | None = None` — appelé par
  `_create_completion_with_retries` avec le délai de chaque `sleep()`
  effectué avant une tentative retentée. **Signature de retour
  inchangée** (`list[ExtractionResult]`) — aucun appelant existant
  (smoke test, tests, `build_task`) ne casse.
- `nuextract_gold_langfuse_eval.build_task` : accumule localement
  (`cold_start_seconds = 0.0`, incrémenté par le callback dans une closure
  propre à chaque appel de `task()`) — thread-safe sous
  `max_concurrency=14`, aucun état partagé entre documents concurrents.
- Sortie de `task()` enrichie :
  `{"extraction_results": [...], "latency_seconds": ..., "cold_start_seconds": ...}`.
- Nouvelle évaluation run-level dans `build_run_evaluator`
  (`nuextract_gold_langfuse_eval.py`, jamais partagée avec LangExtract) :
  `extraction_latency_p50_seconds`/`_p95_seconds`, calculés sur
  `latency_seconds - cold_start_seconds` par item, via `_percentile`
  réutilisé (déjà importé de `gold_dataset_eval.py`). `latency_p50/p95`
  existant (mesure brute, cold-start inclus) **reste inchangé** — les deux
  coexistent, la version "nettoyée" s'ajoute, ne remplace rien.

**Nommage honnête :** le callback se déclenche sur toute tentative
retentée (`InternalServerError`/`APIConnectionError`), pas exclusivement
un cold-start Modal — un crash/redémarrage serveur en cours de run (comme
l'"Item 0" resté en `503` malgré les retries lors du dernier run réel)
déclencherait le même comptage. `cold_start_seconds` reste le nom choisi
(le cas dominant observé en pratique), avec ce caveat en commentaire dans
le code.

## Key Assumptions to Validate

- [x] Le callback `on_retry` est effectivement thread-safe sous la
      concurrence réelle de Langfuse (chaque `task()` a sa propre closure,
      aucun état module-level partagé) — implémenté et testé (`cold_start_seconds`
      local à chaque appel de `task()`, aucune variable globale/module
      touchée par `on_retry`) ; correction en cours de route : `sleep`
      résolu dans le corps de `_create_completion_with_retries` plutôt
      qu'en défaut lié à l'import, sinon invisible à un `monkeypatch` de
      test.
- [ ] `extraction_latency_p50/p95` donne des chiffres cohérents et plus
      bas que `latency_p50/p95` sur le prochain run réel — sinon le
      découpage ne capture pas ce qu'on croit capturer.

## MVP Scope

**In :**
- `on_retry` sur `extract()`/`_create_completion_with_retries`.
- `cold_start_seconds` dans la sortie de `build_task`.
- `extraction_latency_p50_seconds`/`_p95_seconds` dans `build_run_evaluator`.
- Tests offline : callback appelé le bon nombre de fois avec les bons
  délais ; calcul de la latence nettoyée correct.

**Out :** distinguer précisément un cold-start Modal d'une autre erreur
transitoire ; appliquer ce mécanisme à LangExtract (pas de retry côté
LangExtract aujourd'hui) ; modifier `gold_dataset_eval.py`.

## Not Doing (and Why)

- **Distinguer cold-start Modal vs. autre erreur transitoire** —
  nécessiterait de corréler avec les logs serveur (`modal app logs`), hors
  scope d'un champ Langfuse calculé côté client ; le nom
  `cold_start_seconds` reste une approximation documentée, pas une
  garantie.
- **Modifier `gold_dataset_eval.py`/`_latency_evaluations`** — même
  contrainte que le reste de ce chantier (fichier jamais touché) ;
  LangExtract n'a pas de mécanisme de retry à instrumenter de la même
  façon.

## Open Questions

Aucune bloquante.
