import pytest
from pydantic import ValidationError

from app.models import ExtractionGrounding, ExtractionResult, Field, FieldCreate


def test_field_type_defaults_to_text():
    field = Field(id=1, key="titre", title="Titre", definition="Définition")
    assert field.type == "text"


@pytest.mark.parametrize("field_type", ["text", "int", "float", "bool", "date"])
def test_field_accepts_each_supported_type(field_type):
    field = Field(
        id=1, key="titre", title="Titre", definition="Définition", type=field_type
    )
    assert field.type == field_type


def test_field_rejects_unsupported_type():
    with pytest.raises(ValidationError):
        Field(
            id=1, key="titre", title="Titre", definition="Définition", type="autre_chose"
        )


def test_field_create_requires_key():
    with pytest.raises(ValidationError):
        FieldCreate(title="Titre", definition="Définition")


def test_field_parses_structured_examples():
    field = Field(
        id=1,
        key="titre",
        title="Titre",
        definition="Définition",
        examples=[{"context": "texte", "value": "10", "source": "doc.pdf"}],
    )
    assert field.examples[0].context == "texte"
    assert field.examples[0].value == "10"
    assert field.examples[0].source == "doc.pdf"


def test_extraction_result_valid_without_grounding():
    result = ExtractionResult(field_title="Titre", value="Contrat")
    assert result.page_number is None
    assert result.text_position is None


def test_extraction_result_evidence_defaults_to_none():
    result = ExtractionResult(field_title="Titre", value="Contrat")
    assert result.evidence is None


def test_extraction_result_accepts_evidence():
    result = ExtractionResult(
        field_title="Titre", value="Contrat", evidence="Le présent Contrat..."
    )
    assert result.evidence == "Le présent Contrat..."


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


def test_extraction_result_valid_without_value_type():
    result = ExtractionResult(field_title="Titre", value="Contrat")
    assert result.value_type is None
    assert result.typed_value is None
    assert result.type_error is None


def test_extraction_result_accepts_typed_value_distinct_from_grounded_value():
    result = ExtractionResult(
        field_title="Avance",
        value="15 % d'avance à la signature du contrat",
        value_type="int",
        typed_value="15",
    )
    assert result.typed_value == "15"
    assert result.value == "15 % d'avance à la signature du contrat"


def test_extraction_result_accepts_valid_typed_value():
    result = ExtractionResult(
        field_title="Âge", value="30", value_type="int", type_error=None
    )
    assert result.value_type == "int"
    assert result.type_error is None


def test_extraction_result_accepts_type_error():
    result = ExtractionResult(
        field_title="Âge",
        value="environ 30 ans",
        value_type="int",
        type_error="valeur non convertible en int",
    )
    assert result.type_error == "valeur non convertible en int"
