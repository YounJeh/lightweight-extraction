# Task List: Tracing Langfuse (minimal)

Plan de référence : [tasks/plan-langfuse-tracing.md](plan-langfuse-tracing.md)

---

## Task 1: Dépendance `langfuse` + variables `.env` ✅

**Description:** Ajouter le SDK Langfuse aux dépendances du projet (`uv add
langfuse` — vérifier au passage le nom exact du package et sa version
courante). Ajouter `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
`LANGFUSE_HOST` (vide par défaut = host Langfuse Cloud US, documenter le host
EU en commentaire si pertinent) dans `.env` et `.env.example`, suivant le
pattern déjà en place (`GOOGLE_GENERATIVE_AI_API_KEY`, `LLM_MODEL`). Rien
n'importe encore `langfuse` dans le code applicatif à ce stade.

**Note découverte à l'implémentation :** le SDK installé (`langfuse==4.14.5`)
est basé OpenTelemetry ; sa variable de host est `LANGFUSE_BASE_URL`
(`LANGFUSE_HOST` existe mais est documentée *deprecated* dans le SDK). Utilisé
`LANGFUSE_BASE_URL` dans `.env.example` au lieu de `LANGFUSE_HOST` comme prévu
initialement — voir Open Questions du plan.

**Acceptance criteria:**
- [x] `uv sync` installe `langfuse` sans erreur
- [x] `.env.example` documente les 3 nouvelles variables (vides, avec
      commentaire d'usage)
- [x] `.env` (réel, non commité) contient les clés Langfuse Cloud de
      l'utilisateur *(à compléter par l'utilisateur — pas de clé Langfuse
      disponible côté agent)*
- [x] `uv run pytest -v` continue de passer intégralement (rien n'utilise
      encore la dépendance) — 2 échecs pré-existants sur `main`, non liés à ce
      changement (voir note ci-dessous)

**Note :** `tests/test_extraction_routes.py::test_post_extraction_with_no_fields_selected_persists_empty_results`
et `::test_get_extraction_run_is_consultable_after_creation` échouent déjà sur
`main` avant ce changement (vérifié par stash) — hors scope de cette tâche,
signalé à l'utilisateur plutôt que corrigé silencieusement.

**Verification:**
- [x] Tests: `uv run pytest -v` (148 passed, 2 pre-existing failures unrelated)
- [x] Build: `uv sync`

**Dependencies:** None

**Files likely touched:**
- `pyproject.toml`
- `uv.lock`
- `.env.example`
- `.env` *(non commité)*

**Estimated scope:** XS (config + lock)

---

## Task 2: `Protocol` `Tracer` + `NoOpTracer` + `build_tracer()` ✅

**Description:** Créer `app/tools/tracer.py` : `Protocol` `Tracer` avec une
seule méthode `trace_extraction(*, provider: str, model_id: str | None,
field_titles: list[str], source_filename: str | None) ->
AbstractContextManager[None]` ; `NoOpTracer` (implémentation par défaut, ne
fait rien — utilisée en tests et quand aucune clé Langfuse n'est présente) ;
`build_tracer() -> Tracer`, qui renvoie `LangfuseTracer` (Task 3) si
`LANGFUSE_PUBLIC_KEY` et `LANGFUSE_SECRET_KEY` sont dans l'environnement,
sinon `NoOpTracer` — import de `LangfuseTracer` fait à l'intérieur de la
fonction (lazy) pour ne pas rendre `langfuse` une dépendance dure au niveau du
module si les clés sont absentes.

**Acceptance criteria:**
- [x] `NoOpTracer().trace_extraction(...)` s'utilise en `with ...:` sans
      lever, quels que soient les kwargs
- [x] `build_tracer()` renvoie une instance de `NoOpTracer` quand les
      variables d'environnement Langfuse sont absentes
- [x] `build_tracer()` ne lève pas d'erreur d'import si `langfuse` n'est pas
      utilisé (clés absentes) — import paresseux vérifié

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_tracer.py` (4 passed)

**Dependencies:** Task 1

**Files likely touched:**
- `app/tools/tracer.py`
- `tests/test_tracer.py`

**Estimated scope:** S (1-2 fichiers)

---

## Checkpoint: Foundation (après Tasks 1-2)
- [ ] `uv sync` installe l'environnement sans erreur
- [ ] `uv run pytest -m "not live"` passe intégralement, aucune régression
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 3: `LangfuseTracer` (implémentation réelle)

**Description:** Vérifier d'abord l'API exacte du SDK Langfuse installé
(nom du client, méthode de création de span/trace, gestion des
tags/metadata, comportement de flush asynchrone — skill
`source-driven-development`, ne pas deviner). Implémenter
`app/tools/langfuse_tracer.py::LangfuseTracer` satisfaisant le `Protocol`
`Tracer` : `trace_extraction` ouvre un span/trace nommé `"ner_extraction"`,
avec tags `[provider, model_id]` (filtrer les `None`) et metadata
`{"field_titles": ..., "source_filename": ...}`, fermé proprement à la sortie
du `with` (succès ou exception). Gérer explicitement le flush si l'API vérifiée
l'exige (voir Open Questions du plan).

**Acceptance criteria:**
- [ ] `LangfuseTracer()` se construit sans clé API explicite en argument (lit
      `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` de
      l'environnement, comme le SDK le permet nativement)
- [ ] `trace_extraction(...)` utilisé en `with` n'avale pas les exceptions
      levées à l'intérieur du bloc (une erreur LangExtract doit toujours
      remonter à l'appelant)
- [ ] Aucun appel réseau réel déclenché par les tests offline (client
      Langfuse mocké/monkeypatché dans `tests/test_langfuse_tracer.py`)

**Verification:**
- [ ] Tests: `uv run pytest -v tests/test_langfuse_tracer.py` (SDK mocké, pas
      de réseau)

**Dependencies:** Task 2

**Files likely touched:**
- `app/tools/langfuse_tracer.py`
- `tests/test_langfuse_tracer.py`

**Estimated scope:** M (API externe à vérifier avant de coder)

---

## Checkpoint: Implémentation (après Task 3)
- [ ] `uv run pytest -m "not live"` passe sans réseau ni clé Langfuse
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 4: Branchement — `LangExtractNerExtractor` + `routes/extraction.py`

**Description:** `LangExtractNerExtractor.__init__(self, tracer: Tracer | None
= None)` (défaut : `build_tracer()`) ; `extract(self, text, fields, *,
source_filename: str | None = None)` enveloppe le corps existant (y compris
l'appel d'arbitrage) dans `with self._tracer.trace_extraction(provider=...,
model_id=model_id, field_titles=[f.title for f in fields],
source_filename=source_filename):`. Même paramètre optionnel
`source_filename` ajouté à `NerExtractor` (`Protocol`) et `MockNerExtractor`
(ignoré) pour un appel uniforme au site d'appel. `routes/extraction.py` passe
`source_filename=pdf.filename` à `ner_extractor.extract(...)`. `app/main.py`
inchangé (le tracer par défaut de `LangExtractNerExtractor()` suffit).

**Acceptance criteria:**
- [ ] `uv run python -m app.main` démarre sans erreur, avec ou sans clés
      Langfuse dans `.env`
- [ ] Appel de `extract(text, fields)` sans `source_filename` (ancien style)
      continue de fonctionner (défaut `None`) — aucune régression sur les
      tests de routes existants
- [ ] `MockNerExtractor.extract` accepte le nouveau kwarg sans erreur

**Verification:**
- [ ] Tests: `uv run pytest -v -m "not live"` (aucune régression)

**Dependencies:** Task 3

**Files likely touched:**
- `app/tools/ner_langextract.py`
- `app/tools/__init__.py` (Protocol `NerExtractor`)
- `app/tools/mock_ner.py`
- `app/routes/extraction.py`

**Estimated scope:** S (4 fichiers, changements ciblés)

---

## Task 5: Vérification manuelle + housekeeping

**Description:** Démarrer l'app avec les vraies clés (Gemini + Langfuse Cloud)
dans `.env`, uploader un PDF réel via l'UI, et confirmer dans le dashboard
Langfuse Cloud qu'une trace `"ner_extraction"` apparaît avec les bons
tags/metadata (provider, model_id, champs, nom de fichier). Documenter dans le
README comment configurer Langfuse (variables `.env`, lien vers le dashboard)
et compléter `.env.example` si besoin.

**Acceptance criteria:**
- [ ] Trace visible dans Langfuse Cloud après un upload réel, avec
      provider/model_id/champs/fichier source corrects
- [ ] `README.md` documente les 3 variables Langfuse et où consulter les
      traces
- [ ] `uv run pytest -m "not live"` passe intégralement

**Verification:**
- [ ] Manuel: upload PDF réel → vérification dashboard Langfuse Cloud
- [ ] Tests: `uv run pytest -m "not live"`

**Dependencies:** Task 4

**Files likely touched:**
- `README.md`
- `.env.example` *(si besoin de préciser le host)*

**Estimated scope:** XS (pas de nouveau code applicatif)

---

## Checkpoint: Complete (après Task 5)
- [ ] Upload d'un PDF réel dans l'UI → trace visible dans Langfuse Cloud
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue finale avec l'utilisateur
