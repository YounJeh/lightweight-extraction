"""Validation locale (pas de LLM, pas de Langfuse) de deux optimisations
candidates pour l'extraction PDF -> texte : baisser `ocr_dpi` (A) et
court-circuiter l'OCR sous un seuil de surface d'image (B). Voir
docs/ideas/validation-optimisation-ocr.md pour le contexte complet.

Mesure, pour chaque config testée, le temps d'extraction et la présence
(sous-chaîne normalisée) de chaque valeur gold non nulle dans le texte
markdown brut produit — pas d'appel NER/LLM, proxy volontairement simple et
gratuit pour isoler l'effet de l'extraction PDF (voir "Not Doing" du plan).

Usage :
    uv run --no-sync python scripts/validate_ocr_tuning.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402
import pymupdf4llm  # noqa: E402
from pymupdf4llm.helpers import utils as pymupdf4llm_utils  # noqa: E402
from pymupdf4llm.helpers.document_layout import select_ocr_function  # noqa: E402

import app.tools.pdf_pymupdf4llm  # noqa: E402,F401 side effect: pymupdf4llm.use_layout(True)
from scripts.gold_dataset_eval import DATA_TEST_DIR  # noqa: E402
from scripts.gold_dataset_sync import GOLD_YAML_PATH, _load_gold_documents  # noqa: E402
from scripts.gold_matching import _normalize_text  # noqa: E402


def load_gold_values(yaml_path: Path = GOLD_YAML_PATH) -> list[tuple[str, str, str]]:
    """(source_file, field_key, value) pour chaque annotation non nulle du
    yaml gold — mêmes documents que `gold_dataset_eval.py`, sans passer par
    Langfuse."""
    documents = _load_gold_documents(yaml_path)
    rows = []
    for doc in documents:
        for field_key, annotation in doc["annotations"].items():
            value = annotation.get("value")
            if value is not None and str(value).strip():
                rows.append((doc["source_file"], field_key, str(value)))
    return rows


def extract_with_config(
    pdf_bytes: bytes, *, ocr_dpi: int, area_skip_threshold: float | None = None
) -> str:
    """Reproduit `PyMuPDF4LlmTextExtractor.extract_text` avec `ocr_dpi` et
    un seuil de saut d'OCR paramétrables — pour tester plusieurs configs
    sans toucher à `app/`. `area_skip_threshold=None` reproduit le
    comportement actuel de l'app à l'identique (aucun saut)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        base_ocr_function = select_ocr_function()
        if not callable(base_ocr_function):
            return pymupdf4llm.to_markdown(
                doc, page_separators=True, ocr_language="fra", ocr_dpi=ocr_dpi
            )

        def ocr_function(page, **kwargs):
            if area_skip_threshold is not None:
                area = pymupdf4llm_utils.analyze_page(page).get("img_area", 0)
                if area < area_skip_threshold:
                    return
            return base_ocr_function(page, **kwargs)

        return pymupdf4llm.to_markdown(
            doc,
            page_separators=True,
            ocr_language="fra",
            ocr_dpi=ocr_dpi,
            ocr_function=ocr_function,
        )
    finally:
        doc.close()


def value_present(text: str, value: str) -> bool:
    return _normalize_text(value) in _normalize_text(text)


if __name__ == "__main__":
    rows = load_gold_values()
    by_file: dict[str, int] = {}
    for source_file, _field_key, _value in rows:
        by_file[source_file] = by_file.get(source_file, 0) + 1

    print(f"{len(rows)} valeurs gold non nulles, {len(by_file)} documents")
    for source_file, count in sorted(by_file.items()):
        exists = (DATA_TEST_DIR / source_file).exists()
        flag = "" if exists else "  <-- FICHIER INTROUVABLE"
        print(f"  {count:2d}  {source_file}{flag}")
