# Choix techniques

Décisions techniques hors périmètre des specs (`specs/`) : arbitrages,
contournements, compromis. Format : contexte → décision → alternatives
écartées.

---

## Déduplication des résultats d'extraction (arbitrage LLM)

**Contexte :** LangExtract chunk le texte (~1000 car.) et interroge chaque
champ sur chaque chunk → un même champ ressort plusieurs fois, avec des
valeurs différentes. Deux causes : chunks sans la valeur (extraction
fantôme, `char_interval=None`) et chunks avec la valeur à plusieurs
endroits du document (extractions groundées mais divergentes). Le chunking
se fait par phrase, sans overlap entre chunks — comportement par défaut de
LangExtract (`langextract/chunking.py`), non paramétré côté app.

**Décision** (`app/tools/ner_langextract.py`) :
- extractions non groundées / vides → ignorées ;
- 0 candidat → champ absent ; 1 candidat → accepté ; N identiques
  (normalisés) → 1ère occurrence ; N distincts → **arbitrage par un 2e
  appel `langextract.extract()`** (le modèle choisit parmi les candidats),
  repli sur la 1ère occurrence si la réponse ne matche rien.

**Écarté :** toujours garder la 1ère occurrence (perd de l'info) ·
concaténer les valeurs (contraire au besoin d'une valeur unique) · second
SDK LLM dédié (inutile, un seul point d'accès LLM suffit) · augmenter
`max_char_buffer` (traite le symptôme, pas les faux positifs).

**Réf :** [specs/dedupe-extraction-results.md](specs/dedupe-extraction-results.md) ·
[tests/test_ner_langextract_dedupe.py](tests/test_ner_langextract_dedupe.py)

---

## OCR des pages scannées (PyMuPDF4LLM + RapidOCR)

**Contexte :** le chemin texte léger de PyMuPDF4LLM
(`use_layout(False)`) ne fait aucun OCR — une page photocopiée/scannée sans
couche texte (ex. page 12 de `104__DEVIS_25110230_VERSION_A03.pdf`, une
photocopie de CGV) ne produisait que le texte accessoire de la page (11
caractères), rien d'exploitable pour le NER.

**Décision** (`app/tools/pdf_pymupdf4llm.py`) : réactivation du moteur
layout (`use_layout(True)`), OCR géré nativement par PyMuPDF4LLM en mode
"si nécessaire" (`use_ocr` par défaut). Backend RapidOCR (`rapidocr`, pas
`rapidocr-onnxruntime`, préféré nativement par PyMuPDF4LLM quand les deux
sont installés) : détection *et* reconnaissance faites par RapidOCR, aucune
dépendance Tesseract sur ce chemin. `ocr_language="fra"` passé en dur
(pas de variable d'environnement) — décision utilisateur.

**Correction (Task 2) — le mode "si nécessaire" n'est pas aussi ciblé
qu'espéré :** vérifié avec `make_ocr_decision`/`analyze_page` sur le PDF de
test réel, `needs_ocr=True` sur les **12 pages** du document, pas seulement
la page 12 photocopiée — de petites images (logo/en-tête, `img_area` ~2-12%)
et graphiques vectoriels présents sur chaque page suffisent à déclencher la
décision. Le texte natif n'est jamais écrasé (l'OCR ne traite que les zones
sans texte lisible, `exec_ocr_full` exclut explicitement les spans de "bon"
texte avant de construire l'image à OCRiser), mais RapidOCR tourne bel et
bien sur la quasi-totalité des pages de ce document (~2 min sur ce PDF de 12
pages), pas juste sur la page scannée. Décision utilisateur (Task 2) :
garder ce comportement natif de PyMuPDF4LLM tel quel plutôt que d'ajouter un
filtre maison (seuil de texte natif) — le signal `pages_ocr` tracé côté
Langfuse (Task 3-4) reflétera donc fidèlement cette réalité plutôt qu'une
distinction "propre" natif/OCR par page.

**Écarts découverts en implémentation :**
- `rapidocr` tire `opencv-python` (non headless), qui exige `libGL.so.1`
  absent des environnements serveur/CI sans X11 → ajout de
  `opencv-python-headless` comme dépendance directe pour forcer un `cv2`
  sans cette dépendance système (les deux packages installent au même
  chemin ; l'ordre alphabétique du lock fait gagner la variante headless,
  vérifié stable sur `uv sync` à froid).
- `ocr_language="fra"` est en réalité un **no-op** avec RapidOCR : ce kwarg
  n'est utilisé que sur le chemin Tesseract "detection-only" de PyMuPDF4LLM ;
  RapidOCR utilise son propre modèle de reconnaissance multilingue sans
  sélecteur de langue dans cette intégration. Gardé quand même (intention
  explicite, filet si le chemin Tesseract est utilisé un jour).
- Réactiver le moteur layout change le format des séparateurs de page
  (`--- end of page=N ---` 0-indexé → `--- end of page.page_number=N ---`
  1-indexé) — `PAGE_SEPARATOR_RE` mis à jour ; sans impact sur la logique de
  comptage de page dans `LangExtractNerExtractor._locate`.

**Écarté :** OCR via vision-LLM (Gemini) — coût par appel supplémentaire,
point d'accès LLM en plus · Tesseract/PaddleOCR — dépendance système binaire
(Tesseract) ou moins mature côté PyMuPDF4LLM · `ocr_language` configurable
via `.env` — pas de besoin multi-langue identifié pour l'instant.

**Réf :** [docs/ideas/pdf-extraction-ocr-tracing.md](docs/ideas/pdf-extraction-ocr-tracing.md) ·
[tasks/plan-pdf-ocr-tracing.md](tasks/plan-pdf-ocr-tracing.md) ·
[tests/test_pdf_pymupdf4llm.py](tests/test_pdf_pymupdf4llm.py)
