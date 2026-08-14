from datetime import date

from app.models import FieldType

_TRUE_TOKENS = {"oui", "vrai", "true", "1"}
_FALSE_TOKENS = {"non", "faux", "false", "0"}


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
        try:
            int(stripped)
        except ValueError:
            return f"« {raw} » n'est pas un entier valide"
        return None

    if field_type == "float":
        try:
            float(stripped)
        except ValueError:
            return f"« {raw} » n'est pas un nombre décimal valide"
        return None

    if field_type == "bool":
        # Ne jamais utiliser bool(str) : toute chaîne non vide est truthy en
        # Python, y compris "non" — d'où cette table de tokens explicite.
        token = stripped.lower()
        if token in _TRUE_TOKENS or token in _FALSE_TOKENS:
            return None
        return f"« {raw} » n'est pas un booléen reconnu (oui/non, vrai/faux, true/false, 1/0)"

    if field_type == "date":
        try:
            date.fromisoformat(stripped)
        except ValueError:
            return f"« {raw} » n'est pas une date au format ISO (AAAA-MM-JJ)"
        return None

    return None
