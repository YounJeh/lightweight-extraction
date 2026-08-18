from app.models import Field
from app.tools.mock_ner import MockNerExtractor
from app.tools.mock_pdf import MockPdfTextExtractor


def test_mock_pdf_extractor_returns_same_text_regardless_of_input():
    extractor = MockPdfTextExtractor()

    text_a = extractor.extract_text(b"fake pdf bytes A")
    text_b = extractor.extract_text(b"totally different bytes")

    assert text_a == text_b
    assert isinstance(text_a, str) and text_a


def test_mock_ner_extractor_returns_one_result_per_field():
    fields = [
        Field(id=1, key="nom", title="Nom", definition="d", examples=[{"context": "Jean"}]),
        Field(id=2, key="date", title="Date", definition="d", examples=[]),
    ]
    extractor = MockNerExtractor()

    results = extractor.extract("texte quelconque", fields)

    assert [r.field_title for r in results] == ["Nom", "Date"]
    assert all(r.source == "mock" for r in results)


def test_mock_ner_extractor_uses_first_example_when_available():
    field = Field(
        id=1,
        key="nom",
        title="Nom",
        definition="d",
        examples=[{"context": "Jean"}, {"context": "Paul"}],
    )
    extractor = MockNerExtractor()

    [result] = extractor.extract("texte", [field])

    assert result.value == "Jean"


def test_mock_ner_extractor_falls_back_when_no_examples():
    field = Field(id=1, key="nom", title="Nom", definition="d", examples=[])
    extractor = MockNerExtractor()

    [result] = extractor.extract("texte", [field])

    assert "Nom" in result.value


def test_mock_ner_extractor_sets_value_type_from_field_without_error():
    field = Field(
        id=1,
        key="date",
        title="Date",
        definition="d",
        examples=[{"context": "2026-08-14"}],
        type="date",
    )
    extractor = MockNerExtractor()

    [result] = extractor.extract("texte", [field])

    assert result.value_type == "date"
    assert result.typed_value == result.value
    assert result.type_error is None


def test_mock_ner_extractor_is_deterministic():
    fields = [Field(id=1, key="nom", title="Nom", definition="d", examples=[])]
    extractor = MockNerExtractor()

    first = extractor.extract("texte", fields)
    second = extractor.extract("texte", fields)

    assert first == second
