import re

import pymupdf
import pymupdf4llm
from pymupdf4llm.helpers.document_layout import select_ocr_function

from app.tools.tracer import Tracer, build_tracer

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
    grounding can recover page numbers without changing this Protocol.

    `last_pages_ocr` exposes, after a call to `extract_text`, the 1-indexed
    page numbers that actually triggered OCR (empty list if none did) — for
    tracing, without changing the Protocol's `extract_text` signature. Reset
    at the start of every call.

    Traces itself via a `Tracer` (same pattern as `LangExtractNerExtractor`)
    — nests inside whatever span is active when `extract_text` is called
    (see `Tracer.trace_run`, opened by the extraction route), so it doesn't
    need `source_filename` to still show up correctly in Langfuse."""

    def __init__(self, tracer: Tracer | None = None):
        self.last_pages_ocr: list[int] = []
        self._tracer = tracer or build_tracer()

    def extract_text(self, pdf_bytes: bytes) -> str:
        self.last_pages_ocr = []
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            with self._tracer.trace_pdf_extraction(
                engine="pymupdf4llm",
                use_layout=True,
                ocr_language=_OCR_LANGUAGE,
                pages_ocr=self.last_pages_ocr,
                page_count=doc.page_count,
                source_filename=None,
            ) as trace:
                text = pymupdf4llm.to_markdown(
                    doc,
                    page_separators=True,
                    ocr_language=_OCR_LANGUAGE,
                    ocr_function=self._tracking_ocr_function(),
                )
                # last_pages_ocr is only populated *during* to_markdown, so
                # the pages_ocr passed above (at span-open time) is stale —
                # send the real value now that OCR has actually run, while
                # keeping the span's duration tied to the real work above.
                trace.set_metadata({"pages_ocr": self.last_pages_ocr})
                trace.set_output(text)
                return text
        finally:
            doc.close()

    def _tracking_ocr_function(self):
        """Wraps PyMuPDF4LLM's own OCR engine resolution (same one it would
        pick internally if `ocr_function=None`) to record, in
        `last_pages_ocr`, which pages it actually gets called for — it's
        only invoked per-page when `make_ocr_decision` (internal to
        PyMuPDF4LLM) decides that page needs it, so this is a real signal,
        not a guess. Returns None if no OCR engine is available, matching
        the "no OCR" behavior `ocr_function=None` would have had."""
        base_ocr_function = select_ocr_function()
        if not callable(base_ocr_function):
            return None

        def wrapped(page, **kwargs):
            self.last_pages_ocr.append(page.number + 1)
            return base_ocr_function(page, **kwargs)

        return wrapped
