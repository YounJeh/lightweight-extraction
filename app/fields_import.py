import csv
import io

import pandas as pd
from pydantic import BaseModel

from app.models import FieldCreate, FieldExample, FieldType

REQUIRED_COLUMNS = {
    "section",
    "label",
    "Nom",
    "Définition",
    "Type",
    "exemple valeur",
    "Exemple texte",
    "source",
}

_TYPE_MAP: dict[str, FieldType] = {
    "TEXT": "text",
    "INT": "int",
    "FLOAT": "float",
    "BOOLEAN": "bool",
    "DATE": "date",
}


class ImportResult(BaseModel):
    fields: list[FieldCreate] = []
    errors: list[str] = []


class _RowError(Exception):
    def __init__(self, line_no: int, key: str, message: str):
        self.line_no = line_no
        self.key = key
        self.message = message
        super().__init__(f"ligne {line_no} ({key or '?'}) : {message}")


def _normalize_type(raw: str, line_no: int, key: str) -> FieldType:
    normalized = _TYPE_MAP.get(raw.strip().upper())
    if normalized is None:
        raise _RowError(
            line_no, key, f"Type '{raw}' invalide (attendu text/int/float/bool/date)"
        )
    return normalized


def _col(row: dict[str, str], name: str) -> str:
    return (row.get(name) or "").strip()


def _row_to_field_create(row: dict[str, str], line_no: int) -> FieldCreate:
    key = _col(row, "label")
    title = _col(row, "Nom")
    definition = _col(row, "Définition")
    if not key:
        raise _RowError(line_no, key, "colonne 'label' vide")
    if not title:
        raise _RowError(line_no, key, "colonne 'Nom' vide")
    if not definition:
        raise _RowError(line_no, key, "colonne 'Définition' vide")

    field_type = _normalize_type(_col(row, "Type"), line_no, key)
    section = _col(row, "section") or None
    context = _col(row, "Exemple texte")
    value = _col(row, "exemple valeur") or None
    source = _col(row, "source") or None
    examples = [FieldExample(context=context, value=value, source=source)] if context else []

    return FieldCreate(
        key=key,
        title=title,
        definition=definition,
        section=section,
        examples=examples,
        type=field_type,
    )


def _rows_from_bytes(content: bytes, filename: str) -> list[dict[str, str]]:
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        df = pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl").fillna("")
        return df.to_dict(orient="records")
    delimiter = "\t" if lower.endswith(".tsv") else ","
    text = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


def import_fields(content: bytes, filename: str) -> ImportResult:
    """Parse + valide tout-ou-rien un fichier de champs (.csv/.tsv/.xlsx).

    Colonnes en plus tolérées. La moindre colonne requise manquante ou ligne
    invalide rejette l'import complet (`fields` vide, `errors` rempli).
    Un `key` apparaissant plusieurs fois dans le fichier : la dernière
    occurrence l'emporte."""
    rows = _rows_from_bytes(content, filename)
    if not rows:
        return ImportResult(errors=["fichier vide"])

    header = set(rows[0].keys())
    missing = REQUIRED_COLUMNS - header
    if missing:
        return ImportResult(errors=[f"colonnes manquantes : {', '.join(sorted(missing))}"])

    fields: dict[str, FieldCreate] = {}
    errors: list[str] = []
    for line_no, row in enumerate(rows, start=2):  # ligne 1 = en-tête
        try:
            field = _row_to_field_create(row, line_no)
        except _RowError as e:
            errors.append(str(e))
            continue
        fields[field.key] = field

    if errors:
        return ImportResult(errors=errors)
    return ImportResult(fields=list(fields.values()))
