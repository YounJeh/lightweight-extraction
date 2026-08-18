"""Réinitialise la base SQLite à zéro : supprime le fichier existant et
recrée le schéma vide via `init_db`.

Usage :
    uv run python scripts/reset_db.py            # demande confirmation
    uv run python scripts/reset_db.py --yes       # sans confirmation
    uv run python scripts/reset_db.py --db-path data/other.db
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import DEFAULT_DB_PATH, get_connection, init_db


def reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
        print(f"Base supprimée : {db_path}")
    else:
        print(f"Aucune base existante à {db_path}, création directe.")

    conn = get_connection(db_path)
    init_db(conn)
    conn.close()
    print(f"Base recréée (schéma vide) : {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Chemin de la base à réinitialiser (défaut : {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Ne pas demander de confirmation avant suppression",
    )
    args = parser.parse_args()

    if not args.yes:
        answer = input(
            f"Supprimer toutes les données de {args.db_path} et recréer une base vide ? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes", "o", "oui"):
            print("Annulé.")
            return

    reset_db(args.db_path)


if __name__ == "__main__":
    main()
