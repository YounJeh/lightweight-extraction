import pymupdf

from scripts.nuextract_client import render_pdf_pages

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _build_pdf(*page_texts: str) -> bytes:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_render_pdf_pages_returns_one_png_per_page_in_order():
    pdf_bytes = _build_pdf("page un", "page deux", "page trois")

    images = render_pdf_pages(pdf_bytes)

    assert len(images) == 3
    assert all(image.startswith(_PNG_MAGIC) for image in images)


def test_render_pdf_pages_on_a_single_page_document():
    pdf_bytes = _build_pdf("seule page")

    images = render_pdf_pages(pdf_bytes)

    assert len(images) == 1
    assert images[0].startswith(_PNG_MAGIC)
