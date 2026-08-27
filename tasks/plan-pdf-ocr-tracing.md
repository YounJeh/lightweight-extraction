# Implementation Plan: Extraction PDF OCR (pages scannées) + tracing Langfuse dédié

Contexte : issu d'une session `idea-refine` (voir
[docs/ideas/pdf-extraction-ocr-tracing.md](../docs/ideas/pdf-extraction-ocr-tracing.md))
— décisions déjà actées par l'utilisateur : backend **RapidOCR** pour
commencer, `ocr_language` **figé en dur à `"fra"`** (pas de variable
d'environnement), et le span Langfuse doit **distinguer natif/OCR par page**
plutôt que juste indiquer "OCR utilisé quelque part dans le document".

## Overview

Aujourd'hui, `PyMuPDF4LlmTextExtractor` force le chemin texte léger de
PyMuPDF4LLM (`pymupdf4llm.use_layout(False)`), donc une page scannée/sans
couche texte (ex. page 12 de `data_test/104__DEVIS_25110230_VERSION_A03.pdf`,
vérifié : 11 caractères de texte, 3 images) ne produit rien d'extractible.
Ce plan réactive le moteur layout de PyMuPDF4LLM avec OCR ciblé (RapidOCR,
français en dur), et ajoute un span Langfuse `pdf_extraction` — frère du span
`ner_extraction` existant dans une même trace de run — qui documente le mode
d'extraction (moteur, langue OCR) et, par page, si le texte vient de l'OCR ou
du texte natif du PDF.

Explicitement hors scope (voir idea doc) : OCR via vision-LLM, backend OCR
alternatif (Tesseract/PaddleOCR), `ocr_language` configurable, surlignage
visuel du PDF dans l'UI, trace Langfuse séparée pour `pdf_extraction`.

## Architecture Decisions

- **`PdfTextExtractor` (Protocol) reste `extract_text(pdf_bytes) -> str`
  inchangé si possible** — même principe que `specs/pdf-ner-real.md` et
  `tasks/plan-langfuse-tracing.md` (ne pas casser les `Protocol` existants
  pour un besoin de tracing). Le signal par page natif/OCR est donc capturé
  par un mécanisme séparé (probablement un hook `ocr_function` passé à
  `pymupdf4llm.to_markdown`, à confirmer/spiker en Task 2) plutôt que par un
  changement de signature. Si le spike montre qu'aucun hook propre n'existe,
  repli explicite sur une heuristique (comparer la longueur du texte natif de
  chaque page, via `pymupdf`, à la longueur du texte final pour cette page) —
  à documenter dans `choix_techniques.md` si retenu.
- **RapidOCR (ONNX) comme backend, pas Tesseract** — décision utilisateur
  (idea doc) : pas de dépendance système/binaire externe, cohérent avec la
  stack actuelle (pas de Tesseract ni PaddleOCR installés). Nouvelle
  dépendance Python dans `pyproject.toml`.
- **`ocr_language="fra"` en dur dans `PyMuPDF4LlmTextExtractor`**, pas de
  variable d'environnement — décision utilisateur explicite, à revisiter
  seulement si un besoin multi-langue apparaît plus tard.
- **Span racine partagé pour nester `pdf_extraction` et `ner_extraction`
  dans une même trace.** Aujourd'hui, `LangfuseTracer.trace_extraction`
  (span `"ner_extraction"`) est ouvert par `LangExtractNerExtractor.extract`
  lui-même et joue le rôle de racine — donc un futur span `pdf_extraction`
  ouvert indépendamment par `PyMuPDF4LlmTextExtractor` produirait une trace
  Langfuse séparée, pas un span frère (écarté explicitement dans l'idea doc).
  Il faut donc un point commun plus haut : `routes/extraction.py` reçoit un
  `Tracer` injecté (nouveau paramètre, même pattern que `pdf_extractor`/
  `ner_extractor`, défaut `build_tracer()`) et ouvre un span racine autour
  des deux appels (`pdf_extractor.extract_text(...)` puis
  `ner_extractor.extract(...)`) — `trace_extraction` existant se nichera
  alors automatiquement dessous via le contexte OTEL (déjà vérifié pour
  `trace_llm_call` dans `tests/test_langfuse_tracer.py::test_trace_llm_call_nested_inside_trace_extraction`,
  même mécanisme).
- **Nouvelle méthode `Tracer.trace_pdf_extraction`** (Protocol + `NoOpTracer`
  + `LangfuseTracer`), span `as_type="span"`, `name="pdf_extraction"` —
  metadata : moteur (`pymupdf4llm`), `use_layout`, `ocr_language`, et le
  détail par page natif/OCR (ex. `{"pages_ocr": [12], "pages_natif": [1..11]}`
  ou équivalent, forme exacte tranchée à l'implémentation).

## Dependency Graph

```
Task 1: Dépendance RapidOCR + réactivation use_layout(True)/OCR (ocr_language="fra")
        dans PyMuPDF4LlmTextExtractor
    │
    ▼
Task 2: Signal par page natif vs OCR (spike : hook ocr_function, sinon heuristique)
    │
    ▼
Checkpoint: Fondation OCR
    │
    ▼
Task 3: Tracer.trace_pdf_extraction (Protocol + NoOpTracer + LangfuseTracer)
    │
    ▼
Task 4: Span racine partagé dans routes/extraction.py (Tracer injecté,
        pdf_extraction + ner_extraction nestés dans une même trace)
    │
    ▼
Checkpoint: Tracing bout-en-bout
    │
    ▼
Task 5: Vérification manuelle (page 12 réelle, dashboard Langfuse si clés
        dispo) + housekeeping (choix_techniques.md)
```

Globalement séquentiel. Task 3 (tracer) ne dépend pas techniquement du
résultat de Task 2 (juste de la forme de données qu'il reçoit) et pourrait
être développée en parallèle si deux sessions sont disponibles — mais vu la
taille réduite du scope, autant rester séquentiel comme pour
`plan-langfuse-tracing.md`.

## Task List

### Phase 1: Fondation OCR

- [ ] Task 1: Dépendance RapidOCR + réactivation layout/OCR (`ocr_language="fra"`)
- [ ] Task 2: Signal par page natif vs OCR

### Checkpoint: Fondation OCR
- [ ] `uv sync` installe l'environnement sans erreur
- [ ] `uv run pytest -m "not live"` passe intégralement, aucune régression
- [ ] Manuel : page 12 de `104__DEVIS_25110230_VERSION_A03.pdf` produit
      désormais du texte exploitable (plus 11 caractères)
- [ ] Manuel : sortie inchangée en qualité sur un PDF texte existant
      (non-régression du moteur layout sur les documents non scannés)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 2: Tracing Langfuse dédié

- [ ] Task 3: `Tracer.trace_pdf_extraction` (Protocol + NoOpTracer + LangfuseTracer)
- [ ] Task 4: Span racine partagé + branchement `routes/extraction.py`

### Checkpoint: Tracing bout-en-bout
- [ ] `uv run pytest -m "not live"` passe sans réseau ni clé Langfuse
- [ ] Test unitaire (fake client) confirme que `pdf_extraction` et
      `ner_extraction` sont bien deux spans d'une même trace, pas deux traces
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 3: Vérification + housekeeping

- [ ] Task 5: Vérification manuelle + `choix_techniques.md`

### Checkpoint: Complete
- [ ] Upload réel de `104__DEVIS_25110230_VERSION_A03.pdf` dans l'UI → texte
      de la page 12 exploitable par le NER
- [ ] Si clés Langfuse configurées : trace visible avec deux spans
      (`pdf_extraction`, `ner_extraction`), détail natif/OCR par page correct
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue finale avec l'utilisateur

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| RapidOCR (ONNX) lourd à installer ou télécharge des poids au premier run dans un environnement sandboxé | Medium | Vérifier `uv sync` + un premier appel OCR réel dès Task 1, avant d'aller plus loin ; documenter tout téléchargement réseau nécessaire au premier usage. |
| Réactiver le moteur layout change le format de sortie même sur les PDF non scannés (tables HTML, reading order) → régression NER silencieuse | Medium | Checkpoint dédié : comparer explicitement la sortie avant/après sur un PDF texte des fixtures existantes (`tests/pdf_fixtures.py`), pas seulement vérifier le cas OCR. |
| Aucun hook propre pour savoir, page par page, si l'OCR a été déclenché (API interne de PyMuPDF4LLM non garantie pour cet usage) | High | Task 2 est un spike explicite avant tout committement ; repli documenté sur une heuristique de longueur de texte natif vs final si aucun hook fiable n'existe. |
| Nouveau paramètre `Tracer` sur `routes/extraction.py`/`create_app` touche un point d'injection stable | Low | Paramètre optionnel, défaut `build_tracer()` — même pattern que `pdf_extractor`/`ner_extractor` déjà en place, aucun appelant existant cassé. |
| Pas de clés Langfuse en dev/CI → impossible de vérifier le span `pdf_extraction` en réel | Low | Tests unitaires avec fake client (comme `test_langfuse_tracer.py`) suffisent pour la CI ; vérification réelle en Task 5 seulement si des clés sont disponibles, sinon signalé comme non vérifié plutôt que simulé. |

## Open Questions

- Mécanisme exact pour capturer le signal par page natif/OCR — à trancher en
  Task 2 (hook `ocr_function` vs heuristique de longueur de texte).
- Forme exacte des metadata `pdf_extraction` dans Langfuse (liste de pages
  OCRisées vs booléen par page vs ratio global) — tranchée à l'implémentation
  de Task 3, en fonction de ce que Task 2 rend disponible.
