"""Matching normalisé par type de champ + classification TP/FP/FN/TN, pour
comparer une extraction du pipeline réel à la valeur gold correspondante.

Convention slot-filling standard (voir Architecture Decisions du plan) :
une valeur extraite incorrecte compte comme 1 FP *et* 1 FN, pas seulement
"faux" — la bonne valeur n'a pas été produite (FN) et une mauvaise l'a été
(FP). Gold vide + extraction vide -> TN, exclu du calcul precision/recall.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.models import FieldType
from app.tools.type_coercion import FALSE_TOKENS, TRUE_TOKENS

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMERIC_TOLERANCE = 1e-6


def _is_present(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _normalize_number(value: str) -> float | None:
    match = _NUMBER_RE.search(value)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def _normalize_date(value: str) -> date | None:
    match = _ISO_DATE_RE.search(value)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        return None


def _normalize_bool(value: str) -> bool | None:
    token = value.strip().casefold()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    return None


def values_match(gold: object, extracted: object, field_type: FieldType) -> bool:
    """True si `extracted` correspond à `gold`, une fois les deux valeurs
    normalisées selon `field_type`. Ne gère pas le cas des valeurs
    manquantes — appelant (`classify_field`) responsable de la présence."""
    gold_str, extracted_str = str(gold), str(extracted)

    if field_type == "text":
        return _normalize_text(gold_str) == _normalize_text(extracted_str)
    if field_type in ("int", "float"):
        gold_num, extracted_num = _normalize_number(gold_str), _normalize_number(extracted_str)
        return (
            gold_num is not None
            and extracted_num is not None
            and abs(gold_num - extracted_num) < _NUMERIC_TOLERANCE
        )
    if field_type == "date":
        gold_date, extracted_date = _normalize_date(gold_str), _normalize_date(extracted_str)
        return gold_date is not None and extracted_date is not None and gold_date == extracted_date
    if field_type == "bool":
        gold_bool, extracted_bool = _normalize_bool(gold_str), _normalize_bool(extracted_str)
        return gold_bool is not None and extracted_bool is not None and gold_bool == extracted_bool
    return gold_str == extracted_str


@dataclass(frozen=True)
class FieldOutcome:
    field_key: str
    kind: str  # "tp" | "fp" | "fn" | "tn"
    # None : pas de page gold à comparer (evidence.page absent) — pas
    # "faux", juste non évaluable. Uniquement peuplé sur un "tp".
    grounding_match: bool | None = None


def classify_field(
    *,
    field_key: str,
    field_type: FieldType,
    gold_value: object,
    gold_page: int | None,
    extracted_value: object,
    extracted_page: int | None,
) -> list[FieldOutcome]:
    """Classe un champ, pour un document, en TP/FP/FN/TN. Une valeur
    extraite incorrecte (gold et extraction présents mais ne matchant pas)
    produit deux outcomes (FP + FN), pas un seul — voir docstring module."""
    gold_present = _is_present(gold_value)
    extracted_present = _is_present(extracted_value)

    if not gold_present and not extracted_present:
        return [FieldOutcome(field_key, "tn")]

    if gold_present and extracted_present and values_match(
        gold_value, extracted_value, field_type
    ):
        grounding_match = (
            None if gold_page is None else gold_page == extracted_page
        )
        return [FieldOutcome(field_key, "tp", grounding_match)]

    outcomes = []
    if extracted_present:
        outcomes.append(FieldOutcome(field_key, "fp"))
    if gold_present:
        outcomes.append(FieldOutcome(field_key, "fn"))
    return outcomes


def precision_recall_f1(
    tp: int, fp: int, fn: int
) -> tuple[float | None, float | None, float | None]:
    """Precision/recall/F1 à partir de compteurs TP/FP/FN poolés (un ou
    plusieurs documents). `None` quand le dénominateur est nul (pas de
    positif prédit pour precision, pas de positif gold pour recall) —
    laissé au consommateur de retomber sur 0.0 pour l'affichage."""
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )
    return precision, recall, f1
