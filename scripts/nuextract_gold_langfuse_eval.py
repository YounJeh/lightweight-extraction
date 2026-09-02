"""Rejoue le pipeline NuExtract (scripts/nuextract_client.py) sur le
Dataset Langfuse "gold-devis" existant, en réutilisant le scoring déjà
pipeline-agnostique de scripts/gold_dataset_eval.py (import direct, aucune
modification de ce fichier) — comparable dans la vue "Dataset Runs" de
Langfuse aux runs LangExtract existants (gold-devis-eval).

Voir docs/ideas/nuextract-langfuse-eval.md et
tasks/plan-nuextract-langfuse-eval.md pour le contexte complet.

`name` (passé à `dataset.run_experiment`) n'a pas besoin d'embarquer une
date : Langfuse auto-génère un `run_name` unique par appel (`name` +
timestamp ISO, voir `DatasetClient.run_experiment` dans le SDK installé —
même mécanisme que l'exemple officiel "Comparing different model
versions") — plusieurs runs avec le même `name` restent des runs Langfuse
distincts et comparables.

Le run réel contre le vrai serveur NuExtract reste à la charge de l'humain
(règle CLAUDE.md — ce chantier n'est pas du DSPy, pas d'exception ici).

Usage :
    uv run python scripts/nuextract_gold_langfuse_eval.py
"""

import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from app.models import ExtractionResult, Field  # noqa: E402
from scripts import nuextract_client  # noqa: E402
from scripts.gold_dataset_eval import DATA_TEST_DIR, load_gold_fields  # noqa: E402

Extractor = Callable[[bytes, list[Field]], list[ExtractionResult]]


def build_task(
    fields_by_key: dict[str, Field],
    *,
    extractor: Extractor | None = None,
    data_test_dir: Path = DATA_TEST_DIR,
):
    """Task callable pour `dataset.run_experiment` — même contrat que
    `gold_dataset_eval.build_task`, sans étape PDF→texte séparée (NuExtract
    lit les pages directement, voir `nuextract_client.extract`) ni
    `ocr_page_count` (ce pipeline n'OCRise rien)."""
    extractor = extractor or nuextract_client.extract

    def task(*, item, **kwargs) -> dict:
        source_file = item.input["source_file"]
        field_keys = item.input["field_keys"]
        fields = [fields_by_key[key] for key in field_keys]

        start = time.perf_counter()
        pdf_bytes = (data_test_dir / source_file).read_bytes()
        results = extractor(pdf_bytes, fields)
        latency_seconds = time.perf_counter() - start

        return {
            "extraction_results": [result.model_dump() for result in results],
            "latency_seconds": latency_seconds,
        }

    return task
