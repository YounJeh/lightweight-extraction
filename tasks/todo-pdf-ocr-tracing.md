# Task List: Extraction PDF OCR (pages scannées) + tracing Langfuse dédié

Plan de référence : [tasks/plan-pdf-ocr-tracing.md](plan-pdf-ocr-tracing.md)

---

## Task 6 (revue de code, avant merge de la PR #4) ✅

**Description :** `/code-review-and-quality` sur le diff de la branche
(Tasks 1-4). Corrigés :

- **Race condition** (`PyMuPDF4LlmTextExtractor`) : `_tracking_ocr_function`
  écrivait dans `self.last_pages_ocr` (état d'instance partagé) au lieu
  d'une liste locale fermée par le closure — deux `extract_text` concurrents
  sur la même instance pouvaient mélanger les pages OCRisées de deux
  documents différents. Fix : liste locale `pages_ocr` par appel,
  `self.last_pages_ocr` assigné une seule fois à la fin.
- **Appel bloquant** (`routes/extraction.py`) : `extract_text` (jusqu'à
  ~2 min avec l'OCR, voir Task 2) tournait en synchrone dans le handler
  `async def post`, gelant toute la boucle d'événements FastHTML pour
  toutes les requêtes pendant ce temps. Fix : `await
  asyncio.to_thread(pdf_extractor.extract_text, pdf_bytes)` — propage les
  contextvars actives (dont le span OTEL de `trace_run`), donc
  `pdf_extraction` continue de se nicher correctement dans la trace.
  C'est ce changement qui rend la race condition ci-dessus réellement
  exploitable (avant, l'appli étant bloquante, deux extractions ne
  pouvaient jamais tourner en même temps) — les deux fixes vont ensemble.
- **Nits** : commentaires dans `langfuse_tracer.py` référençant les
  fichiers `tasks/plan-pdf-ocr-tracing.md`/`tasks/todo-pdf-ocr-tracing.md`
  (éphémères, risque de rot) retirés — le raisonnement tient seul. Ligne
  vide manquante dans `routes/extraction.py`. Constante `_USE_LAYOUT`
  introduite pour éviter la duplication `True`/`True` entre
  `pymupdf4llm.use_layout(...)` et les metadata de `trace_pdf_extraction`.

**Non corrigé, noté FYI** : le contournement `opencv-python` +
`opencv-python-headless` (Task 1) repose sur un ordre d'installation
déterministe (`uv sync`) non vérifié sur un déploiement Cloud Run réel — à
confirmer au prochain déploiement.

**Verification:**
- [x] Tests: `uv run pytest -m "not live"` (180 passed, 1 échec pré-existant
      sans rapport)
- [x] Manuel: smoke test bout-en-bout via `TestClient` sur le PDF réel après
      le passage à `asyncio.to_thread` — `status 200`,
      `last_pages_ocr == [1..12]` correct

**Dependencies:** Task 4

**Files likely touched:**
- `app/tools/pdf_pymupdf4llm.py`
- `app/tools/langfuse_tracer.py`
- `app/routes/extraction.py`

**Estimated scope:** S (corrections ciblées, pas de nouveau comportement)

---

## Task 1: Dépendance RapidOCR + réactivation layout/OCR (`ocr_language="fra"`) ✅

**Description:** Ajouter le backend RapidOCR (ONNX, ex. `rapidocr-onnxruntime`
— vérifier au passage le nom exact du package et sa compatibilité avec
`pymupdf4llm==1.28.2` installé, cf. `pymupdf4llm/ocr/detect_rapidocr.py`) aux
dépendances du projet. Dans `app/tools/pdf_pymupdf4llm.py`, remplacer
`pymupdf4llm.use_layout(False)` par `pymupdf4llm.use_layout(True)`, et passer
`ocr_language="fra"` (en dur) à `pymupdf4llm.to_markdown(...)`. Laisser
`use_ocr`/`force_ocr` à leurs défauts (`use_ocr=True`, `force_ocr=False` —
mode "OCR si nécessaire", pas sur toutes les pages).

**Notes découvertes à l'implémentation :**
- Package retenu : `rapidocr` (3.9.2, le nouveau package unifié), pas
  `rapidocr-onnxruntime` (l'ancien) — `pymupdf4llm.helpers.document_layout.select_ocr_function()`
  préfère explicitement `rapidocr` quand les deux sont disponibles (aucune
  dépendance Tesseract sur ce chemin : détection *et* reconnaissance faites
  par RapidOCR, contrairement au mode "detection-only" qui nécessite
  Tesseract).
- `rapidocr` tire `opencv-python` (non headless), qui exige `libGL.so.1`
  (absent de ce container/des images serveur sans X11) → `ImportError:
  libGL.so.1` au premier appel OCR. Fix : ajout explicite de
  `opencv-python-headless` comme dépendance directe du projet — les deux
  packages installent un module `cv2` au même chemin, `opencv-python-headless`
  gagne car il est résolu/installé après `opencv-python` dans le lock (ordre
  alphabétique, vérifié stable sur `uv sync` à froid).
- **`ocr_language="fra"` est un no-op avec RapidOCR** : le kwarg `language`
  n'est utilisé que sur le chemin Tesseract "detection-only"
  (`exec_ocr_interface.exec_ocr_detection`/`get_text`) ; `exec_ocr_full`
  (celui réellement appelé avec RapidOCR) accepte `language` dans sa
  signature mais ne s'en sert jamais — RapidOCR utilise son propre modèle de
  reconnaissance multilingue sans sélecteur de langue explicite dans cette
  intégration. Gardé quand même (intention explicite, filet si un jour le
  chemin Tesseract est utilisé) — voir `choix_techniques.md`.
- **Format des séparateurs de page changé** sur le chemin layout :
  `--- end of page=N ---` (0-indexé) → `--- end of page.page_number=N ---`
  (1-indexé). `PAGE_SEPARATOR_RE` mis à jour en conséquence ; la logique de
  comptage dans `LangExtractNerExtractor._locate` n'a pas besoin de changer
  (elle compte les occurrences, ne lit pas le nombre encodé).

**Acceptance criteria:**
- [x] `uv sync` installe RapidOCR sans erreur
- [x] `PyMuPDF4LlmTextExtractor.extract_text` appelle `to_markdown` avec le
      moteur layout actif et `ocr_language="fra"`
- [x] Sur le PDF réel `104__DEVIS_25110230_VERSION_A03.pdf`, le texte de la
      page 12 (photocopie/scan) n'est plus vide — vérifié directement plutôt
      que sur un PDF synthétique (voir Verification)
- [x] `tests/test_pdf_pymupdf4llm.py` existants passent — format des
      séparateurs adapté (voir note ci-dessus), pas supprimé

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_pdf_pymupdf4llm.py` (3 passed)
- [x] Build: `uv sync`
- [x] Manuel: page 12 de `104__DEVIS_25110230_VERSION_A03.pdf` passe de 11
      caractères (`"Page 12/12"`) à ~17 600 caractères de texte réel (CGV).
      **Correction (Task 2) :** contrairement à ce qui était noté ici
      initialement, l'OCR se déclenche en réalité sur les 12 pages du
      document (logo/en-tête présents sur chaque page), pas seulement la
      page 12 — voir `choix_techniques.md`. Le texte natif n'est pas écrasé,
      mais ce n'est pas le comportement "ciblé" annoncé au départ.
- [x] Non-régression : `uv run pytest -m "not live"` — 171 passed, 1 échec
      pré-existant sans rapport (`test_post_fields_import_replaces_definition_on_same_key`,
      lié à une modification locale non commitée de `DATASET GOLD.csv`
      antérieure à cette session, confirmé par `git stash`)

**Dependencies:** None

**Files likely touched:**
- `pyproject.toml`
- `uv.lock`
- `app/tools/pdf_pymupdf4llm.py`
- `tests/test_pdf_pymupdf4llm.py`

**Estimated scope:** S (1-2 fichiers + dépendance)

---

## Task 2: Signal par page natif vs OCR ✅

**Description:** Spike : déterminer si PyMuPDF4LLM expose un moyen fiable de
savoir, page par page, si l'OCR a été déclenché sur le chemin layout (ex. en
enveloppant le paramètre `ocr_function`, ou via un autre hook interne trouvé
en Task 1). Si oui, implémenter la capture de ce signal dans
`PyMuPDF4LlmTextExtractor` (nouvel attribut exposé après un appel, ex.
`last_pages_ocr: list[int]`, sans changer la signature du `Protocol`
`extract_text`). Si aucun hook fiable n'existe, implémenter le repli
heuristique documenté dans le plan (comparer, page par page via `pymupdf`, la
longueur du texte natif à celle du texte final) et documenter ce choix dans
`choix_techniques.md`.

**Hook retenu :** `select_ocr_function()` (fonction publique de
`pymupdf4llm.helpers.document_layout`, celle-là même que PyMuPDF4LLM utilise
en interne pour résoudre l'engine OCR par défaut) est appelée une fois par
`extract_text`, puis enveloppée dans une closure qui enregistre
`page.number + 1` dans `self.last_pages_ocr` avant de déléguer à la fonction
réelle — passée explicitement comme `ocr_function=` à `to_markdown`. Pas de
repli heuristique nécessaire : le hook existe et est fiable (n'est appelé
que quand `make_ocr_decision`, interne à PyMuPDF4LLM, décide qu'une page en
a besoin).

**Découverte importante (corrige une affirmation erronée de la Task 1) :**
vérifié sur le PDF réel que le hook enregistre les **12 pages** comme
OCRisées, pas seulement la page 12 — `needs_ocr=True` sur chaque page à
cause de petites images (logo/en-tête) et graphiques vectoriels présents
partout dans le document, pas seulement sur la page effectivement
photocopiée. Le texte natif n'est jamais écrasé (voir
`choix_techniques.md`), mais le signal `last_pages_ocr` reflète cette
réalité — sur ce document, il vaut `[1..12]`, pas `[12]`. Confirmé avec
l'utilisateur (Task 2) : comportement natif de la lib gardé tel quel plutôt
que d'ajouter un filtre maison sur la longueur de texte natif.

**Acceptance criteria:**
- [x] Sur un PDF mixte (une page texte natif + une page image-only,
      construite en mémoire dans le test), le mécanisme retenu identifie
      correctement quelle page a nécessité l'OCR
- [x] Le `Protocol` `PdfTextExtractor.extract_text(pdf_bytes) -> str` n'est
      pas modifié — le signal est porté par un canal séparé
      (`last_pages_ocr`) sur `PyMuPDF4LlmTextExtractor`
- [x] Mécanisme retenu (hook `ocr_function`, pas d'heuristique) documenté

**Verification:**
- [x] Tests: `tests/test_pdf_pymupdf4llm.py` — 2 nouveaux tests sur un PDF
      mixte natif/scanné construit en mémoire (`_build_mixed_pdf`) : le hook
      identifie bien la page scannée (`last_pages_ocr == [2]`), et se
      réinitialise correctement entre deux appels
- [x] Manuel: sur `104__DEVIS_25110230_VERSION_A03.pdf`,
      `last_pages_ocr == [1, 2, ..., 12]` — voir découverte ci-dessus, pas
      `[12]` comme attendu initialement dans ce plan

**Dependencies:** Task 1

**Files likely touched:**
- `app/tools/pdf_pymupdf4llm.py`
- `tests/test_pdf_pymupdf4llm.py`
- `choix_techniques.md`

**Estimated scope:** M (spike + implémentation, incertitude technique réelle)

---

## Checkpoint: Fondation OCR (après Tasks 1-2) ✅
- [x] `uv sync` installe l'environnement sans erreur
- [x] `uv run pytest -m "not live"` passe (173 passed, 1 échec pré-existant
      sans rapport, confirmé par `git stash` — voir Task 1)
- [x] Manuel : page 12 de `104__DEVIS_25110230_VERSION_A03.pdf` produit
      désormais du texte exploitable (~17 600 caractères de CGV)
- [x] Manuel : `test_extract_text_returns_real_content_for_each_page`
      confirme l'absence de régression sur un PDF texte natif (contenu +
      ordre des pages inchangés)
- [x] Revue avec l'utilisateur : décision de garder le comportement OCR natif
      de PyMuPDF4LLM tel quel (OCR déclenché sur quasi toutes les pages à
      cause des logos, pas seulement les pages scannées — voir Task 2)

---

## Task 3: `Tracer.trace_pdf_extraction` (Protocol + NoOpTracer + LangfuseTracer) ✅

**Description:** Ajouter au `Protocol` `Tracer` (`app/tools/tracer.py`) une
méthode `trace_pdf_extraction(*, engine: str, use_layout: bool, ocr_language:
str, pages_ocr: list[int], pages_natif: list[int]) ->
AbstractContextManager[ObservationHandle]` (forme exacte des kwargs à ajuster
selon ce que Task 2 produit). `NoOpTracer` : implémentation vide, même pattern
que `trace_extraction`/`trace_llm_call`. `LangfuseTracer.trace_pdf_extraction`
ouvre un span `as_type="span"`, `name="pdf_extraction"`, avec les infos
moteur/OCR en `metadata` (pas en `input`/`output` — pas de texte source à
loguer deux fois, déjà porté par `ner_extraction`).

**Notes à l'implémentation :**
- Signature finale : `page_count: int` remplace `pages_natif: list[int]` — le
  compte total de pages suffit avec `pages_ocr`, pas besoin de lister les
  pages natives explicitement (`page_count - len(pages_ocr)` suffit si
  besoin côté dashboard).
- Metadata passée directement via `start_as_current_observation(...,
  metadata=...)` — vérifié que le SDK Langfuse installé (`langfuse==4.14.5`)
  accepte ce kwarg nativement sur `start_as_current_observation`, pas besoin
  de `propagate_attributes` (qui sert aux tags/metadata de la trace racine,
  pas d'un span enfant) — plus simple que ce qui était anticipé dans le plan.
- `input=source_filename` (peut être `None`) plutôt que rien — cohérent avec
  le fait que `set_output` reste disponible sur le handle pour y poser le
  texte extrait si besoin plus tard.

**Acceptance criteria:**
- [x] `NoOpTracer().trace_pdf_extraction(...)` s'utilise en `with ...:` sans
      lever, quels que soient les kwargs
- [x] `LangfuseTracer.trace_pdf_extraction` ouvre bien un span nommé
      `"pdf_extraction"` avec `as_type="span"` et les metadata attendues
      (vérifié via fake client, même pattern que
      `tests/test_langfuse_tracer.py`)
- [x] Aucun appel réseau réel déclenché par les tests offline

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_tracer.py tests/test_langfuse_tracer.py`
      (15 passed)
- [x] Non-régression : `uv run pytest -m "not live"` (176 passed, 1 échec
      pré-existant sans rapport)

**Dependencies:** Task 2

**Files likely touched:**
- `app/tools/tracer.py`
- `app/tools/langfuse_tracer.py`
- `tests/test_tracer.py`
- `tests/test_langfuse_tracer.py`

**Estimated scope:** S (2-3 fichiers, pattern déjà établi par
`trace_extraction`/`trace_llm_call`)

---

## Task 4: Span racine partagé + branchement `routes/extraction.py` ✅

**Description:** Injecter un `Tracer` dans `register_extraction_routes`
(nouveau paramètre optionnel, défaut `build_tracer()` — même pattern que
`pdf_extractor`/`ner_extractor`). Dans le handler `POST /extraction`, ouvrir
un span racine (ex. `name="extraction_run"`) qui englobe l'appel
`pdf_extractor.extract_text(pdf_bytes)` (imbriquant
`tracer.trace_pdf_extraction(...)`) puis `ner_extractor.extract(...)` (dont le
`trace_extraction` existant se niche automatiquement dessous via le contexte
OTEL actif, sans modification de `LangExtractNerExtractor`). `app/main.py`
passe le `Tracer` partagé aux deux outils si nécessaire, ou laisse chacun
utiliser son propre `build_tracer()` par défaut (les deux renvoient le même
type de tracer, donc compatible tant que le span racine est ouvert au bon
endroit).

**Notes à l'implémentation :**
- `Tracer.trace_run(*, source_filename)` ajouté (Protocol + NoOpTracer +
  LangfuseTracer) : span `"extraction_run"`, flush dans son `finally` — cette
  méthode devient le vrai point d'entrée/racine de la trace, ouverte dans
  `routes/extraction.py::post` autour des deux appels
  (`pdf_extractor.extract_text` puis `ner_extractor.extract`).
- `PyMuPDF4LlmTextExtractor` devient tracer-aware (constructeur
  `tracer: Tracer | None = None`, même pattern que
  `LangExtractNerExtractor`) et appelle lui-même `trace_pdf_extraction` en
  interne — le `Protocol` `extract_text(pdf_bytes) -> str` reste inchangé,
  la route n'a pas besoin de connaître `last_pages_ocr` (accès direct
  impossible de toute façon si un autre `PdfTextExtractor` est injecté, ex.
  `MockPdfTextExtractor`).
- **Bug découvert et corrigé pendant l'implémentation :** `pages_ocr`
  ne peut pas être passé correctement à l'ouverture du span
  `trace_pdf_extraction` (avant que `to_markdown()` ne tourne, donc
  `last_pages_ocr` est encore vide à ce moment). Ajout de
  `ObservationHandle.set_metadata(metadata)` (Protocol + `_NoOpSpan` +
  `_SpanHandle`, même principe que `set_output`) pour mettre à jour les
  metadata *après* l'extraction, une fois `last_pages_ocr` réellement
  peuplé — tout en gardant le span ouvert pendant toute la durée réelle de
  l'OCR (utile pour voir le coût temps dans Langfuse).
- `app/main.py` inchangé — chaque composant (`pdf_extractor`, `ner_extractor`,
  route) résout son propre `build_tracer()` par défaut ; comme tous
  partagent le même client Langfuse singleton sous-jacent
  (`get_client()`), le nesting OTEL fonctionne même avec des instances
  Python `LangfuseTracer` différentes.
- **Limite acceptée (non vérifiable sans compte Langfuse Cloud réel) :**
  `trace_run` n'appelle pas `propagate_attributes(trace_name=...)` — c'est
  `trace_extraction` (nested) qui pose le nom de la trace
  (`"ner_extraction"`), donc un span enfant portera le même nom que la trace
  elle-même dans le dashboard. Cosmétique, pas fonctionnel ; à revisiter en
  Task 5 si ça s'avère confus en usage réel.

**Acceptance criteria:**
- [x] `uv run python -m app.main` démarre sans erreur, avec ou sans clés
      Langfuse dans `.env`
- [x] Un upload PDF déclenche un span racine unique contenant `pdf_extraction`
      puis `ner_extraction` comme enfants (vérifié via fake client : un seul
      appel `start_as_current_observation` racine, les deux autres imbriqués
      — `test_trace_pdf_extraction_and_trace_extraction_nest_inside_trace_run`)
- [x] Aucune régression sur `tests/test_extraction_routes.py` (17 passed)

**Verification:**
- [x] Tests: `uv run pytest -v -m "not live"` (180 passed, 1 échec
      pré-existant sans rapport)
- [x] Manuel: smoke test bout-en-bout — upload réel de
      `104__DEVIS_25110230_VERSION_A03.pdf` via `TestClient` (vrai
      `PyMuPDF4LlmTextExtractor`, `MockNerExtractor` pour éviter un appel
      Gemini payant) → `status: 200`, log confirme l'OCR sur les 12 pages,
      run persisté et consultable

**Dependencies:** Task 3

**Files likely touched:**
- `app/tools/tracer.py`
- `app/tools/langfuse_tracer.py`
- `app/tools/pdf_pymupdf4llm.py`
- `app/routes/extraction.py`
- `tests/test_tracer.py`
- `tests/test_langfuse_tracer.py`
- `tests/test_pdf_pymupdf4llm.py`

**Estimated scope:** S-M (branchement ciblé, mais touche le point d'entrée
de la route)

---

## Checkpoint: Tracing bout-en-bout (après Tasks 3-4) ✅
- [x] `uv run pytest -m "not live"` passe sans réseau ni clé Langfuse
      (180 passed, 1 échec pré-existant sans rapport)
- [x] Test unitaire (fake client) confirme que `pdf_extraction` et
      `ner_extraction` sont bien deux spans d'une même trace, pas deux traces
      séparées
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 5: Vérification manuelle + housekeeping

**Description:** Démarrer l'app avec les vraies clés (Gemini + Langfuse Cloud
si disponibles) dans `.env`, uploader `104__DEVIS_25110230_VERSION_A03.pdf`
via l'UI, et confirmer que la page 12 contribue désormais des valeurs
extraites (ou au moins du texte exploitable transmis au NER). Si des clés
Langfuse sont configurées, confirmer dans le dashboard qu'une trace montre
les deux spans (`pdf_extraction`, `ner_extraction`) avec le détail natif/OCR
par page. Documenter la décision (RapidOCR retenu, `ocr_language="fra"` en
dur, mécanisme de détection natif/OCR) dans `choix_techniques.md`, suivant le
format déjà utilisé (contexte → décision → alternatives écartées).

**Acceptance criteria:**
- [ ] Page 12 du PDF réel produit du texte exploitable après upload dans l'UI
- [ ] Si clés Langfuse configurées : trace visible avec les deux spans et le
      détail natif/OCR par page correct ; sinon, signalé comme non vérifié
- [ ] `choix_techniques.md` documente la décision RapidOCR + `ocr_language`
      en dur + mécanisme retenu pour le signal natif/OCR
- [ ] `uv run pytest -m "not live"` passe intégralement

**Verification:**
- [ ] Manuel: upload PDF réel → vérification page 12 + dashboard Langfuse
      (si clés dispo)
- [ ] Tests: `uv run pytest -m "not live"`

**Dependencies:** Task 4

**Files likely touched:**
- `choix_techniques.md`
- `README.md` *(si la config OCR nécessite une note d'installation)*

**Estimated scope:** XS-S (pas de nouveau code applicatif, vérification +
documentation)

---

## Checkpoint: Complete (après Task 5)
- [ ] Upload réel de `104__DEVIS_25110230_VERSION_A03.pdf` dans l'UI → texte
      de la page 12 exploitable par le NER
- [ ] Si clés Langfuse configurées : trace visible avec deux spans
      (`pdf_extraction`, `ner_extraction`), détail natif/OCR par page correct
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue finale avec l'utilisateur
