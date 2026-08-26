import pytest

from app.models import Field
from app.tools.ner_langextract import _build_example, _typed_hint


@pytest.mark.parametrize(
    "example, field_type, expected",
    [
        ("10 % d’avance à la signature du contrat", "int", "10"),
        ("environ 3,5 jours de retard", "float", "3.5"),
        ("Le paiement est dû le 2026-08-14 au plus tard", "date", "2026-08-14"),
        ("Aucun motif clair ici", "int", None),
    ],
)
def test_typed_hint_narrows_example_to_typed_substring(example, field_type, expected):
    assert _typed_hint(example, field_type) == expected


def test_typed_hint_returns_none_for_text_type_input():
    # _typed_hint n'est jamais appelé pour "text" en pratique (voir
    # _build_example), mais ne doit rien casser si on l'appelle quand même.
    assert _typed_hint("n'importe quoi", "text") is None


def test_typed_hint_returns_none_for_bool_type_input():
    # Idem pour "bool" : la valeur typée est dérivée par _typed_value (voir
    # test_ner_langextract_dedupe.py), jamais isolée depuis l'exemple.
    assert _typed_hint("Le client a payé : oui", "bool") is None


def test_build_example_sets_narrowed_attributes_value_for_typed_field():
    field = Field(
        id=1,
        key="pourcentage_avance",
        title="pourcentage_avance",
        definition="d",
        examples=[{"context": "10 % d’avance à la signature du contrat"}],
        type="int",
    )

    example = _build_example([field])

    assert example.extractions[0].extraction_text == "10 % d’avance à la signature du contrat"
    assert example.extractions[0].attributes == {"value": "10"}


def test_build_example_omits_attributes_when_no_hint_found():
    field = Field(
        id=1,
        key="motif",
        title="motif",
        definition="d",
        examples=[{"context": "Aucun motif clair ici"}],
        type="int",
    )

    example = _build_example([field])

    assert example.extractions[0].attributes is None


def test_build_example_omits_attributes_for_text_fields():
    field = Field(
        id=1,
        key="nom",
        title="Nom",
        definition="d",
        examples=[{"context": "Jean Dupont"}],
        type="text",
    )

    example = _build_example([field])

    assert example.extractions[0].attributes is None


def test_build_example_omits_attributes_for_bool_fields():
    field = Field(
        id=1,
        key="has_penalite",
        title="Pénalité",
        definition="d",
        examples=[{"context": "Une pénalité de retard est prévue au contrat."}],
        type="bool",
    )

    example = _build_example([field])

    assert example.extractions[0].attributes is None
