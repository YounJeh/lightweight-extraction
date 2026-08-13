import pymupdf

from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor


def _build_pdf(*page_texts: str) -> bytes:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extract_text_returns_real_content_for_each_page():
    pdf_bytes = _build_pdf("Titre: Contrat de bail", "Date de signature: 12 janvier 2024")

    text = PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)

    assert "Titre: Contrat de bail" in text
    assert "Date de signature: 12 janvier 2024" in text
    assert text.index("Titre") < text.index("Date de signature")


def test_extract_text_marks_page_boundaries():
    pdf_bytes = _build_pdf("Page une", "Page deux")

    text = PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)

    assert "--- end of page=0 ---" in text
    assert "--- end of page=1 ---" in text
    assert text.index("Page une") < text.index("end of page=0")
    assert text.index("end of page=0") < text.index("Page deux")


def test_extract_text_marks_single_page_boundary():
    pdf_bytes = _build_pdf("Seule page du document")

    text = PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)

    assert "Seule page du document" in text
    assert "--- end of page=0 ---" in text
