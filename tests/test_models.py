import pytest
from pydantic import ValidationError

from app.models import ExtractionGrounding, ExtractionResult


def test_extraction_result_valid_without_grounding():
    result = ExtractionResult(field_title="Titre", value="Contrat")
    assert result.page_number is None
    assert result.text_position is None


def test_extraction_result_accepts_grounding():
    result = ExtractionResult(
        field_title="Titre",
        value="Contrat",
        source="langextract",
        page_number=2,
        text_position="...le Contrat signé...",
    )
    assert result.page_number == 2
    assert result.text_position == "...le Contrat signé..."


def test_extraction_grounding_requires_all_fields():
    with pytest.raises(ValidationError):
        ExtractionGrounding(result_id=1, page_number=1)
