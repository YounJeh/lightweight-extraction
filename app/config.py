import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = _ENV_PATH) -> None:
    """Charge les paires KEY=VALUE de .env dans os.environ (sans écraser une
    variable déjà présente). Pas de dépendance externe (python-dotenv) pour
    un besoin aussi simple — un seul fichier, deux variables."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()
