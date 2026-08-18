import io
from pathlib import Path

import pandas as pd

from app.fields_import import REQUIRED_COLUMNS, import_fields

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GOLD_CSV_PATH = _REPO_ROOT / "DATASET GOLD.csv"

_HEADER = list(REQUIRED_COLUMNS)
_VALID_ROW = {
    "section": "Pénalité",
    "label": "pourcentage_penalite_retard",
    "Nom": "Pénalité de retard",
    "Définition": "Pourcentage de pénalité par jour de retard",
    "Type": "INT",
    "exemple valeur": "2",
    "Exemple texte": "Pénalité de retard de 2% du montant des travaux par jour.",
    "source": "contrat.pdf",
}


def _csv_bytes(rows: list[dict[str, str]], header: list[str] = _HEADER) -> bytes:
    df = pd.DataFrame(rows, columns=header)
    return df.to_csv(index=False).encode("utf-8")


def _tsv_bytes(rows: list[dict[str, str]], header: list[str] = _HEADER) -> bytes:
    df = pd.DataFrame(rows, columns=header)
    return df.to_csv(index=False, sep="\t").encode("utf-8")


def _xlsx_bytes(rows: list[dict[str, str]], header: list[str] = _HEADER) -> bytes:
    df = pd.DataFrame(rows, columns=header)
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_import_real_gold_dataset_csv_has_no_errors():
    content = _GOLD_CSV_PATH.read_bytes()

    result = import_fields(content, "DATASET GOLD.csv")

    assert result.errors == []
    assert len(result.fields) == 96


def test_import_valid_csv_row_produces_expected_field_create():
    result = import_fields(_csv_bytes([_VALID_ROW]), "fields.csv")

    assert result.errors == []
    [field] = result.fields
    assert field.key == "pourcentage_penalite_retard"
    assert field.title == "Pénalité de retard"
    assert field.type == "int"
    assert field.section == "Pénalité"
    assert field.examples[0].context == _VALID_ROW["Exemple texte"]
    assert field.examples[0].value == "2"
    assert field.examples[0].source == "contrat.pdf"


def test_import_missing_column_rejects_whole_file_with_error_listing_it():
    header = [c for c in _HEADER if c != "source"]
    content = _csv_bytes([{k: v for k, v in _VALID_ROW.items() if k != "source"}], header)

    result = import_fields(content, "fields.csv")

    assert result.fields == []
    assert len(result.errors) == 1
    assert "source" in result.errors[0]


def test_import_invalid_type_rejects_whole_file():
    bad_row = {**_VALID_ROW, "label": "autre_champ", "Type": "PERCENT"}
    content = _csv_bytes([_VALID_ROW, bad_row])

    result = import_fields(content, "fields.csv")

    assert result.fields == []
    assert any("PERCENT" in e for e in result.errors)
    assert any("autre_champ" in e for e in result.errors)


def test_import_extra_columns_are_tolerated():
    row = {**_VALID_ROW, "colonne_en_plus": "ignorée"}
    content = _csv_bytes([row], _HEADER + ["colonne_en_plus"])

    result = import_fields(content, "fields.csv")

    assert result.errors == []
    assert len(result.fields) == 1


def test_import_tsv_produces_same_result_as_csv():
    result = import_fields(_tsv_bytes([_VALID_ROW]), "fields.tsv")

    assert result.errors == []
    assert result.fields[0].key == "pourcentage_penalite_retard"


def test_import_xlsx_produces_same_result_as_csv():
    result = import_fields(_xlsx_bytes([_VALID_ROW]), "fields.xlsx")

    assert result.errors == []
    assert result.fields[0].key == "pourcentage_penalite_retard"
    assert result.fields[0].examples[0].value == "2"


def test_import_cp1252_encoded_csv_is_decoded_correctly():
    content = _csv_bytes([_VALID_ROW]).decode("utf-8").encode("cp1252")

    result = import_fields(content, "export_excel.csv")

    assert result.errors == []
    assert result.fields[0].definition == _VALID_ROW["Définition"]


def test_import_malformed_xlsx_returns_error_instead_of_crashing():
    result = import_fields(b"not a real xlsx file", "fields.xlsx")

    assert result.fields == []
    assert len(result.errors) == 1


def test_import_duplicate_key_in_same_file_keeps_last_occurrence():
    first = {**_VALID_ROW, "Nom": "Ancien nom"}
    second = {**_VALID_ROW, "Nom": "Nouveau nom"}
    content = _csv_bytes([first, second])

    result = import_fields(content, "fields.csv")

    assert result.errors == []
    assert len(result.fields) == 1
    assert result.fields[0].title == "Nouveau nom"
