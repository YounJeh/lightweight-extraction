"""Client pour un serveur NuExtract auto-hébergé (vLLM, API compatible
OpenAI) — pipeline de comparaison, jamais utilisé par l'app en production.

Voir specs/nuextract-pipeline-spike.md pour le contexte complet.
"""

import pymupdf

_RENDER_DPI = 150


def render_pdf_pages(pdf_bytes: bytes, *, dpi: int = _RENDER_DPI) -> list[bytes]:
    """Rend chaque page du PDF en PNG (une image par page, dans l'ordre du
    document). NuExtract ne prend pas de PDF en entrée directement — ses
    exemples officiels attendent des images (voir specs/nuextract-pipeline-spike.md,
    section Tech Stack)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]
    finally:
        doc.close()
