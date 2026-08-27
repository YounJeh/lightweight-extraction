"""Rejoue le pipeline d'extraction réel sur le dataset gold
(tests/data/dataset_gold_devis.yaml) et trace le résultat dans Langfuse.

Voir specs/ci-eval-gold-dataset.md pour le contexte complet.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import get_connection, init_db
from app.fields_import import import_fields
from app.models import Field
from app.repository import FieldRepository

GOLD_FIELDS_CSV = (
    Path(__file__).resolve().parent.parent / "tests" / "data" / "gold_devis_fields.csv"
)


def load_gold_fields(csv_path: Path = GOLD_FIELDS_CSV) -> list[Field]:
    """Charge les définitions des champs du dataset gold depuis un CSV
    git-trackée (tests/data/gold_devis_fields.csv — DATASET GOLD.csv à la
    racine est obsolète pour ce chantier, voir specs/ci-eval-gold-dataset.md)
    et les seed dans une base SQLite jetable pour obtenir des `Field` réels
    (avec `id`), sans jamais toucher à data/app.db (gitignoré/éphémère,
    absent d'un runner CI frais)."""
    result = import_fields(csv_path.read_bytes(), csv_path.name)
    if result.errors:
        raise ValueError(f"gold_devis_fields.csv invalide : {result.errors}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "gold_eval.db"
        conn = get_connection(db_path)
        try:
            init_db(conn)
            repo = FieldRepository(conn)
            return [repo.upsert_by_key(field) for field in result.fields]
        finally:
            conn.close()
