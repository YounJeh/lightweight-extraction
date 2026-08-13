import re

import pymupdf
import pymupdf4llm

# PyMuPDF4LLM defaults to a GNN-based layout/OCR engine, which is heavy and
# non-deterministic for the plain-text PDFs this project targets; force the
# lightweight "rag" text-extraction path instead.
pymupdf4llm.use_layout(False)

# Native PyMuPDF4LLM page-separator format (page_separators=True), reused by
# LangExtractNerExtractor to map character offsets back to a page number.
PAGE_SEPARATOR_RE = re.compile(r"\n\n--- end of page=(\d+) ---\n\n")


class PyMuPDF4LlmTextExtractor:
    """PdfTextExtractor backed by PyMuPDF4LLM. Page boundaries are preserved
    in the returned text via PyMuPDF4LLM's native page separators, so
    grounding can recover page numbers without changing this Protocol."""

    def extract_text(self, pdf_bytes: bytes) -> str:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            return pymupdf4llm.to_markdown(doc, page_separators=True)
        finally:
            doc.close()
