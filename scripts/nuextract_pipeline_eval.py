"""Rejoue le pipeline NuExtract (scripts/nuextract_client.py) sur le
dataset gold et produit un CSV de scores comparable au pipeline actuel
(scripts/gold_dataset_eval.py) — jamais intégré à l'app en production.

Script autonome, pas de Dataset Langfuse (contrairement à
gold_dataset_eval.py) : la comparaison porte d'abord sur la qualité
d'extraction, pas sur le tracing. Voir specs/nuextract-pipeline-spike.md.

Le run réel contre le vrai serveur NuExtract reste à la charge de l'humain
(règle CLAUDE.md — ce chantier n'est pas du DSPy, pas d'exception ici).

Usage :
    uv run python scripts/nuextract_pipeline_eval.py [--limit N]
"""

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from app.models import ExtractionResult, Field  # noqa: E402
from scripts import nuextract_client  # noqa: E402
from scripts.gold_dataset_eval import DATA_TEST_DIR, load_gold_fields  # noqa: E402
from scripts.gold_dataset_sync import GOLD_YAML_PATH, _load_gold_documents  # noqa: E402
from scripts.gold_matching import FieldOutcome, classify_field, precision_recall_f1  # noqa: E402

DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "tasks" / "nuextract-pipeline-eval-results.csv"
)
_CSV_FIELDNAMES = [
    "document_id",
    "source_file",
    "field_key",
    "gold_value",
    "extracted_value",
    "match",
    "latency_seconds",
]

Extractor = Callable[[bytes, list[Field]], list[ExtractionResult]]


def run_document(
    doc: dict[str, Any],
    fields_by_key: dict[str, Field],
    *,
    extractor: Extractor,
    data_test_dir: Path = DATA_TEST_DIR,
) -> dict[str, Any]:
    """Rejoue le pipeline NuExtract sur un document gold et classe chaque
    champ demandé (TP/FP/FN/TN) contre l'annotation gold — même convention
    que `build_field_evaluator` (`scripts/gold_dataset_eval.py`) : la
    valeur comparée est `typed_value` en priorité, `value` en repli.
    `extractor` injectable pour les tests offline (mock) ; en usage réel,
    `nuextract_client.extract`. `extracted_page=None` partout (pas de
    grounding en v1, voir specs/nuextract-pipeline-spike.md)."""
    field_keys = sorted(doc["annotations"].keys())
    fields = [fields_by_key[key] for key in field_keys]
    pdf_bytes = (data_test_dir / doc["source_file"]).read_bytes()

    start = time.perf_counter()
    results = extractor(pdf_bytes, fields)
    latency_seconds = time.perf_counter() - start
    results_by_key = {field.key: result for field, result in zip(fields, results)}

    rows: list[dict[str, Any]] = []
    outcomes: list[FieldOutcome] = []
    for field in fields:
        annotation = doc["annotations"][field.key]
        result = results_by_key.get(field.key)
        extracted_value = (result.typed_value or result.value) if result else None

        field_outcomes = classify_field(
            field_key=field.key,
            field_type=field.type,
            gold_value=annotation.get("value"),
            gold_page=(annotation.get("evidence") or {}).get("page"),
            extracted_value=extracted_value,
            extracted_page=None,
        )
        outcomes.extend(field_outcomes)
        rows.append(
            {
                "document_id": doc["document_id"],
                "source_file": doc["source_file"],
                "field_key": field.key,
                "gold_value": annotation.get("value"),
                "extracted_value": extracted_value,
                "match": "/".join(o.kind for o in field_outcomes),
                "latency_seconds": f"{latency_seconds:.2f}",
            }
        )

    return {"rows": rows, "outcomes": outcomes}


def aggregate_scores(all_outcomes: list[FieldOutcome]) -> dict[str, dict[str, float]]:
    """Précision/recall/F1 par champ, poolés sur tous les documents — même
    convention que `_field_metrics_evaluations` (`scripts/gold_dataset_eval.py`)."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    for outcome in all_outcomes:
        counts[outcome.field_key][outcome.kind] += 1

    scores = {}
    for field_key, c in counts.items():
        precision, recall, f1 = precision_recall_f1(c["tp"], c["fp"], c["fn"])
        scores[field_key] = {
            "precision": precision or 0.0,
            "recall": recall or 0.0,
            "f1": f1 or 0.0,
            **c,
        }
    return scores


def write_results_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def run(
    *,
    extractor: Extractor | None = None,
    gold_yaml_path: Path = GOLD_YAML_PATH,
    data_test_dir: Path = DATA_TEST_DIR,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    limit: int | None = None,
) -> dict[str, dict[str, float]]:
    """`limit` : ne rejoue que les `limit` premiers documents du YAML gold
    — pour valider le tuyau sur 2-3 documents avant un run complet (voir
    Open Questions, specs/nuextract-pipeline-spike.md)."""
    extractor = extractor or nuextract_client.extract
    fields_by_key = {field.key: field for field in load_gold_fields()}
    documents = _load_gold_documents(gold_yaml_path)
    if limit is not None:
        documents = documents[:limit]

    all_rows: list[dict[str, Any]] = []
    all_outcomes: list[FieldOutcome] = []
    for doc in documents:
        result = run_document(
            doc, fields_by_key, extractor=extractor, data_test_dir=data_test_dir
        )
        all_rows.extend(result["rows"])
        all_outcomes.extend(result["outcomes"])

    write_results_csv(all_rows, output_path)
    return aggregate_scores(all_outcomes)


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Ne rejoue que les N premiers documents du gold (défaut : tous)",
    )
    args = parser.parse_args()

    scores = run(limit=args.limit)
    for field_key, s in scores.items():
        print(
            f"{field_key}: precision={s['precision']:.2f} recall={s['recall']:.2f} "
            f"f1={s['f1']:.2f} (tp={s['tp']} fp={s['fp']} fn={s['fn']} tn={s['tn']})"
        )
    print(f"\nDétail par document : {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
