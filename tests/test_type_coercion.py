import pytest

from app.tools.type_coercion import validate


def test_text_always_valid():
    assert validate("n'importe quoi", "text") is None
    assert validate("", "text") is None


@pytest.mark.parametrize("raw", ["30", "-4", "0"])
def test_int_accepts_valid_integers(raw):
    assert validate(raw, "int") is None


@pytest.mark.parametrize("raw", ["environ 30", "3.5", "trente"])
def test_int_rejects_invalid_values(raw):
    assert validate(raw, "int") is not None


@pytest.mark.parametrize("raw", ["3.5", "-2.1", "10"])
def test_float_accepts_valid_numbers(raw):
    assert validate(raw, "float") is None


def test_float_rejects_non_numeric():
    assert validate("trois virgule cinq", "float") is not None


@pytest.mark.parametrize("raw", ["oui", "non", "vrai", "faux", "true", "false", "1", "0", "OUI"])
def test_bool_accepts_known_tokens(raw):
    assert validate(raw, "bool") is None


def test_bool_does_not_use_python_truthiness_on_non_token():
    # Piège explicite : bool("peut-être") vaut True en Python natif, mais ce
    # n'est pas un token reconnu -> doit être rejeté ici.
    assert validate("peut-être", "bool") is not None


def test_date_accepts_iso_format():
    assert validate("2026-08-14", "date") is None


def test_date_rejects_non_iso_format():
    assert validate("14 août 2026", "date") is not None


@pytest.mark.parametrize("field_type", ["int", "float", "bool", "date"])
def test_empty_value_invalid_for_non_text_types(field_type):
    assert validate("", field_type) is not None
    assert validate("   ", field_type) is not None
