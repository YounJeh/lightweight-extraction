import re

import pymupdf
import pymupdf4llm

# GNN-based layout engine, needed for OCR: a scanned/photocopied page (no
# text layer) is otherwise silently skipped by the lightweight "rag" path
# (see choix_techniques.md — page 12 of a real devis PDF returned 11 chars
# of text). use_ocr defaults to "select" mode (OCR only pages that need it),
# so this doesn't mean OCR-ing every page of every document.
pymupdf4llm.use_layout(True)

# Native PyMuPDF4LLM page-separator format (page_separators=True), reused by
# LangExtractNerExtractor to map character offsets back to a page number.
# Format changed when the layout engine was reactivated for OCR support:
# "end of page=N" (0-indexed) -> "end of page.page_number=N" (1-indexed) —
# only the literal format matters here, LangExtractNerExtractor._locate just
# counts occurrences, it doesn't read the embedded number.
PAGE_SEPARATOR_RE = re.compile(r"\n\n--- end of page\.page_number=(\d+) ---\n\n")

# Hardcoded rather than an env var (decision recorded in
# docs/ideas/pdf-extraction-ocr-tracing.md) — revisit if multi-language
# documents show up.
_OCR_LANGUAGE = "fra"


class PyMuPDF4LlmTextExtractor:
    """PdfTextExtractor backed by PyMuPDF4LLM. Page boundaries are preserved
    in the returned text via PyMuPDF4LLM's native page separators, so
    grounding can recover page numbers without changing this Protocol."""

    def extract_text(self, pdf_bytes: bytes) -> str:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            return pymupdf4llm.to_markdown(
                doc, page_separators=True, ocr_language=_OCR_LANGUAGE
            )
        finally:
            doc.close()
