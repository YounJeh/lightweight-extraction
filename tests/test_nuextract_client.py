import json

import pymupdf

from app.models import Field
from scripts.nuextract_client import build_template, extract, parse_response, render_pdf_pages

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _field(key: str, type_: str = "text") -> Field:
    return Field(id=1, key=key, title=f"Titre {key}", definition="def", type=type_)


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


def test_build_template_maps_every_field_to_verbatim_string():
    fields = [_field("numero_devis"), _field("montant", "float")]

    template = build_template(fields)

    assert template == {"numero_devis": "verbatim-string", "montant": "verbatim-string"}


def test_parse_response_maps_present_fields_with_type_coercion():
    fields = [_field("numero_devis"), _field("pourcentage", "int")]
    content = json.dumps({"numero_devis": "n°6952", "pourcentage": "30"})

    results = parse_response(content, fields)

    by_title = {r.field_title: r for r in results}
    assert by_title["Titre numero_devis"].value == "n°6952"
    assert by_title["Titre numero_devis"].typed_value == "n°6952"
    assert by_title["Titre numero_devis"].source == "nuextract"
    assert by_title["Titre pourcentage"].typed_value == "30"
    assert by_title["Titre pourcentage"].type_error is None


def test_parse_response_flags_a_value_that_does_not_coerce_to_the_field_type():
    fields = [_field("pourcentage", "int")]
    content = json.dumps({"pourcentage": "trente"})

    results = parse_response(content, fields)

    assert results[0].type_error is not None


def test_parse_response_produces_an_empty_row_for_a_missing_or_blank_field():
    fields = [_field("numero_devis"), _field("nom_societe")]
    content = json.dumps({"numero_devis": "  ", "autre_champ": "valeur"})

    results = parse_response(content, fields)

    by_title = {r.field_title: r for r in results}
    assert by_title["Titre numero_devis"].value == ""
    assert by_title["Titre numero_devis"].typed_value is None
    assert by_title["Titre nom_societe"].value == ""


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content
        self.received_kwargs: dict | None = None

    def create(self, **kwargs):
        self.received_kwargs = kwargs
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, content: str):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _FakeCompletions(content)


def test_extract_sends_one_image_per_page_and_the_verbatim_string_template():
    pdf_bytes = _build_pdf("page un", "page deux")
    fields = [_field("numero_devis")]
    fake_client = _FakeClient(json.dumps({"numero_devis": "n°6952"}))

    results = extract(pdf_bytes, fields, client=fake_client)

    kwargs = fake_client.chat.completions.received_kwargs
    assert len(kwargs["messages"][0]["content"]) == 2  # une image par page
    template = json.loads(kwargs["extra_body"]["chat_template_kwargs"]["template"])
    assert template == {"numero_devis": "verbatim-string"}
    assert results[0].value == "n°6952"
    assert results[0].source == "nuextract"
