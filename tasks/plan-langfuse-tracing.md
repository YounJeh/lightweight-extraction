# Implementation Plan: Tracing Langfuse (minimal)

Contexte : issu d'une session `idea-refine` (voir conversation) — objectif retenu
par l'utilisateur : tracing/debug des appels LLM, Langfuse Cloud (free tier),
maintenant (avant l'étape 2 roadmap), scope volontairement réduit. Pas de spec
séparée : ce plan fait office de source de vérité.

## Overview

Ajouter une trace Langfuse autour de chaque extraction NER réelle
(`LangExtractNerExtractor.extract`), taguée provider/model_id/champs/fichier
source, pour combler l'absence totale de logs sur le seul point d'appel LLM du
pipeline aujourd'hui (`app/tools/ner_langextract.py`). Implémenté derrière un
`Protocol` `Tracer` (même pattern que `NerExtractor`/`PdfTextExtractor`), avec
une implémentation `NoOpTracer` par défaut en tests et `LangfuseTracer` quand
des clés Langfuse sont présentes dans l'environnement — swappable vers un
self-host plus tard sans toucher au reste du code. Explicitement hors scope :
dataset gold / versioning Langfuse, système d'évaluation (precision/recall),
self-host Docker, tracing du reste du pipeline (PDF extraction).

## Architecture Decisions

- **Révision (Task 3) — capture input/output, pas seulement tags/metadata.**
  Le SDK vérifié expose `start_as_current_observation(..., input=...)` et
  `span.update(output=...)`, qui permettent de voir le texte source et le
  résultat de l'extraction dans le dashboard — sans ça, une trace ne montre
  que "ça a tourné, avec ces tags", ce qui rate l'objectif principal retenu à
  l'idéation ("voir chaque prompt/completion"). `Tracer.trace_extraction`
  prend donc `text` en plus, et le context manager cède (`yield`) un
  `TraceHandle` avec une seule méthode `set_output(output)`, appelée par
  `LangExtractNerExtractor.extract` juste avant de retourner ses résultats.
  `NoOpTracer` cède un `_NoOpSpan` dont `set_output` ne fait rien.
- **Tags/metadata via `propagate_attributes` (SDK vérifié), pas un paramètre
  `tags` sur le span lui-même** — le SDK Langfuse installé (`langfuse==4.14.5`,
  OTEL-based) n'expose pas de kwarg `tags` sur `start_as_current_observation`
  ; les tags/metadata de trace passent par le context manager dédié
  `propagate_attributes(trace_name=..., tags=..., metadata=...)`, imbriqué
  juste à l'intérieur du span racine (ordre requis par le SDK — voir
  docstring `propagate_attributes`).
- **`Tracer` en context manager, pas en décorateur.** Un décorateur `@observe`
  appliqué au niveau de la fonction ne permettrait pas d'injecter un
  `NoOpTracer` en tests ni de swapper l'implémentation à la construction,
  contrairement au pattern d'injection déjà en place pour `NerExtractor`. Le
  `Protocol` expose donc `trace_extraction(...) -> AbstractContextManager[None]`,
  utilisé en `with self._tracer.trace_extraction(...):` autour du corps de
  `LangExtractNerExtractor.extract` (y compris l'appel d'arbitrage interne
  `_arbitrate`, qui fait partie de la même extraction logique — pas de
  sous-span séparé, on reste au niveau "une extraction = une trace").
- **Activation par présence des clés, pas par flag dédié.** `build_tracer()`
  renvoie `LangfuseTracer` si `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` sont
  présentes dans l'environnement (chargées via `app/config.py::load_env()`,
  déjà en place), sinon `NoOpTracer` — même logique que le routing
  Gemini/OpenAI existant (`_api_key_for`), pas de nouvelle variable
  `LANGFUSE_ENABLED`.
- **Extension mineure et rétrocompatible du `Protocol` `NerExtractor`** pour
  faire transiter `source_filename` (déjà connu dans `routes/extraction.py`
  via `pdf.filename`, mais jamais passé à `extract` aujourd'hui) : un paramètre
  keyword-only `source_filename: str | None = None` sur `extract`, avec la
  même signature ajoutée à `MockNerExtractor` (ignoré, juste pour satisfaire
  l'appel uniforme du site d'appel). Défaut `None` partout : aucun appel
  existant ne casse. **Point à trancher/simplifiable** : si l'utilisateur
  préfère ne pas toucher au `Protocol` du tout, ce paramètre (et le tag
  fichier source) peut être abandonné sans impact sur le reste du plan — voir
  Risks.
- **Pas de nouveau test `live` dédié.** Le test `@pytest.mark.live` existant
  (`tests/test_ner_langextract_live.py`) continue de passer tel quel avec un
  `NoOpTracer` (pas de clé Langfuse requise en CI). La vérification que
  Langfuse reçoit bien la trace se fait manuellement (checkpoint), pas par un
  test automatisé qui dépendrait d'un compte Langfuse Cloud réel.
- **API exacte du SDK Langfuse vérifiée à l'implémentation (Task 3), pas
  devinée** : `get_client()` (singleton, lit les variables d'environnement du
  SDK), `client.start_as_current_observation(as_type="span", name=...,
  input=...)` (context manager), `span.update(output=...)`,
  `propagate_attributes(trace_name=..., tags=..., metadata=...)`,
  `client.flush()`. Flush **synchrone après chaque trace** (dans un
  `finally`, donc même en cas d'exception) plutôt qu'un hook de shutdown :
  vérifié que `flush()` ne lève pas d'exception même si l'export réseau
  échoue (retries internes du SDK, log un warning) — voir Task 3.

## Dependency Graph

```
Task 1: Dépendance langfuse + variables .env (LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST)
    │
    ▼
Task 2: Protocol Tracer + NoOpTracer + build_tracer()
    │
    ▼
Task 3: LangfuseTracer (implémentation réelle, API vérifiée)
    │
    ▼
Task 4: Branchement dans LangExtractNerExtractor + routes/extraction.py
         (source_filename), main.py inchangé (tracer par défaut via build_tracer())
    │
    ▼
Task 5: Vérification manuelle + housekeeping (README, .env.example)
```

Séquentiel de bout en bout — chaque tâche dépend directement de la précédente,
pas de parallélisation utile vu la taille du scope.

## Task List

### Phase 1: Foundation

- [ ] Task 1: Dépendance `langfuse` + variables `.env`/`.env.example`
- [ ] Task 2: `Protocol` `Tracer` + `NoOpTracer` + `build_tracer()`

### Checkpoint: Foundation
- [ ] `uv sync` installe l'environnement sans erreur
- [ ] `uv run pytest -m "not live"` passe intégralement, aucune régression
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 2: Implémentation Langfuse

- [ ] Task 3: `LangfuseTracer` (SDK réel, API vérifiée avant implémentation)

### Checkpoint: Implémentation
- [ ] `uv run pytest -m "not live"` passe sans réseau ni clé (LangfuseTracer
      non exercé par défaut, `NoOpTracer` utilisé dans les tests)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 3: Branchement + vérification

- [ ] Task 4: Branchement dans `LangExtractNerExtractor` + `routes/extraction.py`
- [ ] Task 5: Vérification manuelle (trace visible dans Langfuse Cloud) +
      housekeeping (README, `.env.example`)

### Checkpoint: Complete
- [ ] Upload d'un PDF réel dans l'UI → trace visible dans le dashboard
      Langfuse Cloud avec provider/model_id/champs/fichier source
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue finale avec l'utilisateur

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| API exacte du SDK Langfuse (méthodes, comportement de flush) inconnue à ce stade | Medium | Vérifier la doc au moment de Task 3 (`source-driven-development`) plutôt que deviner ; span créé via un context manager isole ce détail dans un seul fichier. |
| Flush asynchrone du client Langfuse : traces perdues si le process se termine avant l'envoi | Medium | Vérifier explicitement à Task 3 s'il faut un `flush()`/`shutdown()` explicite après chaque requête ou au shutdown de l'app FastHTML ; à défaut le confirmer par le checkpoint manuel (trace bien visible dans le dashboard après une requête réelle). |
| Extension du `Protocol` `NerExtractor` (Task 4, `source_filename`) touche un contrat que le plan précédent avait explicitement laissé intact | Low | Changement additif/rétrocompatible (kwarg optionnel, défaut `None`) ; si l'utilisateur préfère zéro changement de `Protocol`, ce tag seul est abandonnable sans impact sur Tasks 1-3. |
| Clés Langfuse Cloud committées par erreur dans `.env` | Low | `.env` déjà hors git (à vérifier en Task 1) ; seul `.env.example` (vide) est commité, comme pour les clés Gemini/OpenAI existantes. |

## Open Questions

Toutes résolues :
- ~~Nom exact du package PyPI et de l'API du SDK Langfuse actuel~~ **Résolu
  (Task 1)** : package `langfuse` (PyPI), version installée `4.14.5` — SDK v3+
  basé OpenTelemetry (dépendances `opentelemetry-*` tirées automatiquement).
  Variables d'environnement lues nativement par le client :
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` (host,
  défaut `https://cloud.langfuse.com`, région EU — région US :
  `https://us.cloud.langfuse.com`). `LANGFUSE_HOST` existe aussi côté SDK mais
  est documenté **deprecated** en faveur de `LANGFUSE_BASE_URL` : c'est ce
  dernier qui est utilisé dans `.env.example` (pas `LANGFUSE_HOST` comme prévu
  initialement dans ce plan).
- ~~Faut-il un `flush()` explicite par requête FastHTML, ou un hook de
  shutdown suffit-il ?~~ **Résolu (Task 3)** : `flush()` synchrone dans un
  `finally` à chaque `trace_extraction`. Vérifié manuellement (script
  autonome, host injoignable) que `flush()` retry en interne (~3s) puis logue
  un warning sans lever — un problème réseau Langfuse ne peut donc pas faire
  planter une extraction, mais ajoute jusqu'à quelques secondes de latence à
  la requête si Langfuse Cloud est injoignable. Acceptable pour ce projet
  (usage local/faible volume) ; à revisiter si ça devient gênant en usage
  réel (flush en tâche de fond, par ex.).
