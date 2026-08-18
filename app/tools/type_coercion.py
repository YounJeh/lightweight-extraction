from collections.abc import Callable
from datetime import date

from app.models import FieldType

_TRUE_TOKENS = {"oui", "vrai", "true", "1"}
_FALSE_TOKENS = {"non", "faux", "false", "0"}


def _convertible(
    raw: str, stripped: str, converter: Callable[[str], object], expected: str
) -> str | None:
    try:
        converter(stripped)
    except ValueError:
        return f"« {raw} » n'est pas {expected}"
    return None


def validate(raw: str, field_type: FieldType) -> str | None:
    """Vérifie que `raw` est convertible dans `field_type`.

    Renvoie None si valide, sinon un message d'erreur explicite. Ne modifie
    jamais `raw` — seule la validité est décidée ici, la valeur affichée
    reste le texte groundé tel quel."""
    if field_type == "text":
        return None

    stripped = raw.strip()
    if not stripped:
        return f"valeur vide, non convertible en {field_type}"

    if field_type == "int":
        return _convertible(raw, stripped, int, "un entier valide")

    if field_type == "float":
        return _convertible(raw, stripped, float, "un nombre décimal valide")

    if field_type == "bool":
        # Ne jamais utiliser bool(str) : toute chaîne non vide est truthy en
        # Python, y compris "non" — d'où cette table de tokens explicite.
        token = stripped.lower()
        if token in _TRUE_TOKENS or token in _FALSE_TOKENS:
            return None
        return f"« {raw} » n'est pas un booléen reconnu (oui/non, vrai/faux, true/false, 1/0)"

    if field_type == "date":
        return _convertible(
            raw, stripped, date.fromisoformat, "une date au format ISO (AAAA-MM-JJ)"
        )

    return None
