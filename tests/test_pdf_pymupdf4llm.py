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


def _build_mixed_pdf(native_text: str, scanned_text: str) -> bytes:
    """Un PDF à deux pages : la première avec du texte natif normal, la
    seconde rendue comme une image (comme une page photocopiée/scannée,
    sans couche texte) — reproduit la situation réelle de la page 12 de
    104__DEVIS_25110230_VERSION_A03.pdf (voir choix_techniques.md)."""
    source = pymupdf.open()
    source_page = source.new_page()
    source_page.insert_text((72, 72), scanned_text)
    pixmap = source_page.get_pixmap(dpi=150)
    source.close()

    doc = pymupdf.open()
    native_page = doc.new_page()
    native_page.insert_text((72, 72), native_text)
    scanned_page = doc.new_page()
    scanned_page.insert_image(scanned_page.rect, pixmap=pixmap)

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

    assert "--- end of page.page_number=1 ---" in text
    assert "--- end of page.page_number=2 ---" in text
    assert text.index("Page une") < text.index("end of page.page_number=1")
    assert text.index("end of page.page_number=1") < text.index("Page deux")


def test_extract_text_marks_single_page_boundary():
    pdf_bytes = _build_pdf("Seule page du document")

    text = PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)

    assert "Seule page du document" in text
    assert "--- end of page.page_number=1 ---" in text


def test_extract_text_records_only_the_scanned_page_as_ocred():
    pdf_bytes = _build_mixed_pdf(
        native_text="Titre: Contrat de bail",
        scanned_text="Conditions generales de vente",
    )
    extractor = PyMuPDF4LlmTextExtractor()

    text = extractor.extract_text(pdf_bytes)

    assert extractor.last_pages_ocr == [2]
    assert "Titre: Contrat de bail" in text


def test_extract_text_resets_last_pages_ocr_between_calls():
    extractor = PyMuPDF4LlmTextExtractor()
    scanned_pdf = _build_mixed_pdf(
        native_text="Titre: Contrat de bail",
        scanned_text="Conditions generales de vente",
    )
    extractor.extract_text(scanned_pdf)
    assert extractor.last_pages_ocr == [2]

    native_only_pdf = _build_pdf("Rien a scanner ici")
    extractor.extract_text(native_only_pdf)

    assert extractor.last_pages_ocr == []
