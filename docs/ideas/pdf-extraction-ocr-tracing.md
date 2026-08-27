# Fiabiliser l'extraction PDF (pages scannées) + traçage Langfuse de la conversion

## Problem Statement
Comment garantir qu'une page PDF sans couche texte (photocopie/scan) produit
quand même une extraction exploitable, et rendre visible dans Langfuse quel
mode d'extraction (modèle + hyperparamètres, natif ou OCR) a été utilisé pour
chaque conversion PDF → texte ?

## Recommended Direction
Réactiver le moteur layout/GNN de PyMuPDF4LLM (`use_layout(True)`) avec OCR
ciblé, backend **RapidOCR** (ONNX, pas de binaire externe) pour commencer,
langue **figée en dur à `"fra"`** pour le moment (pas de variable
d'environnement à ce stade). Le mode OCR par défaut de PyMuPDF4LLM
("OCR si nécessaire") ne déclenche l'OCR que sur les pages sans texte
exploitable, pas sur tout le document — ça limite le risque de coût/
non-déterminisme qui avait motivé la désactivation initiale du moteur
layout.

En parallèle, faire remonter l'ouverture de trace Langfuse au niveau de la
route d'extraction pour qu'un nouveau span `pdf_extraction` (extracteur,
mode layout, langue OCR, **et surtout : par page, si l'OCR a été déclenché
ou si le texte natif a suffi**) et le span `ner_extraction` existant soient
frères dans une même trace de run. Ce marquage par page est ce qui permet de
distinguer dans Langfuse un run "tout texte natif" d'un run "partiellement
OCRisé".

## Key Assumptions to Validate
- [ ] Les séparateurs de page (`--- end of page=N ---`) sont préservés à
      l'identique sur le chemin layout → tester sur un PDF réel, vérifier
      que `LangExtractNerExtractor._locate` continue de fonctionner sans
      modification.
- [ ] RapidOCR (ONNX) est installable et suffisant en qualité pour du
      français sur des devis/marchés scannés → tester sur la page 12 du
      fichier `104__DEVIS_25110230_VERSION_A03.pdf`, comparer la valeur
      extraite à l'attendu.
- [ ] Réactiver le moteur layout ne dégrade pas la qualité/format sur les
      pages *non* scannées déjà bien traitées aujourd'hui → comparer la
      sortie markdown avant/après sur un doc texte simple du dataset gold.
- [ ] Le cas est réellement fréquent dans le corpus → audit rapide de
      `data_test/` et du corpus réel (compter les pages à texte quasi-nul).
- [ ] Le coût CPU/temps de l'OCR (même ciblé) reste acceptable pour l'usage
      interactif de l'app (upload → résultat affiché).
- [ ] PyMuPDF4LLM expose bien, page par page, si l'OCR a été déclenché ou
      non (nécessaire pour le marquage natif/OCR par page dans le span
      Langfuse) — à confirmer dans l'API layout avant implémentation.

## MVP Scope
- `pymupdf4llm.use_layout(True)` + `ocr_language="fra"` (en dur) dans
  `PyMuPDF4LlmTextExtractor`.
- Ajout de la dépendance RapidOCR (ONNX) dans `pyproject.toml`.
- Nouveau span Langfuse `pdf_extraction` (extracteur, `use_layout`,
  `ocr_language="fra"`, et détail par page natif vs OCR) rattaché au même
  run/trace que `ner_extraction` — nécessite de faire remonter l'ouverture
  de trace au niveau route.
- Vérification manuelle sur `104__DEVIS_25110230_VERSION_A03.pdf` (page 12)
  + non-régression sur un doc texte existant du dataset gold.

## Not Doing (and Why)
- **OCR via vision-LLM (Gemini)** — écarté ; garde un point d'accès LLM en
  moins et évite un coût par appel supplémentaire, mais perd la possibilité
  de comparer les deux approches sur ce cas précis si RapidOCR déçoit en
  qualité française.
- **Autres backends OCR (Tesseract, PaddleOCR)** — RapidOCR retenu comme
  point de départ (pas de dépendance système, cohérent avec la philosophie
  "lightweight" du projet) ; à réévaluer seulement si la qualité déçoit.
- **`ocr_language` configurable via `.env`** — écarté pour l'instant, figé
  à `"fra"` en dur ; à revisiter si le besoin de multi-langue apparaît.
- **Surlignage visuel du PDF / bounding box OCR dans l'UI** — hors périmètre
  déjà acté dans `specs/pdf-ner-real.md`, pas remis en cause ici.
- **Détection/flag sans OCR (option intermédiaire)** — écartée : extraction
  réelle visée directement, pas juste la visibilité du trou.
- **Trace Langfuse séparée `pdf_extraction` indépendante** — écartée au
  profit d'un span nesté dans le même run, pour garder une seule trace par
  extraction (plus facile à corréler dans Langfuse).
