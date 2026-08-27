"""Rejoue le pipeline d'extraction réel sur le dataset gold
(tests/data/dataset_gold_devis.yaml) et trace le résultat dans Langfuse.

Voir specs/ci-eval-gold-dataset.md pour le contexte complet.
"""

import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.fields_import import import_fields  # noqa: E402
from app.models import Field  # noqa: E402
from app.repository import FieldRepository  # noqa: E402
from app.tools.ner_langextract import LangExtractNerExtractor  # noqa: E402
from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor  # noqa: E402
from scripts.gold_dataset_sync import DATASET_NAME  # noqa: E402
from scripts.gold_matching import classify_field  # noqa: E402

GOLD_FIELDS_CSV = (
    Path(__file__).resolve().parent.parent / "tests" / "data" / "gold_devis_fields.csv"
)
DATA_TEST_DIR = Path(__file__).resolve().parent.parent / "data_test"


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


def build_task(
    fields_by_key: dict[str, Field],
    *,
    pdf_extractor: Any = None,
    ner_extractor: Any = None,
    data_test_dir: Path = DATA_TEST_DIR,
):
    """Task callable pour `dataset.run_experiment` — enveloppe fine du
    pipeline réel (`PyMuPDF4LlmTextExtractor` + `LangExtractNerExtractor`),
    aucune réimplémentation (voir Architecture Decisions du plan). Les deux
    extracteurs sont injectables pour les tests hors réseau ; en usage réel,
    laissés à leur valeur par défaut (`build_tracer()` résout le vrai
    `LangfuseTracer`, comme en production).

    `item.input` (posé par `gold_dataset_sync.sync_gold_dataset`) contient
    `source_file` et `field_keys` — la liste de clés à extraire pour ce
    document, résolue ici en objets `Field` réels (avec `id`/`title`,
    nécessaires à `LangExtractNerExtractor.extract`).

    La sortie est un dict (pas juste la liste de résultats) : `latency_seconds`
    (mesurée ici en wall-clock — pas de dépendance à l'API Langfuse, qui a un
    délai d'indexation et ne conviendrait pas à un évaluateur run-level
    synchrone) et `ocr_page_count` (`pdf_extractor.last_pages_ocr`, pour le
    split OCR/non-OCR du run-level, Task 6) accompagnent
    `extraction_results`."""
    pdf_extractor = pdf_extractor or PyMuPDF4LlmTextExtractor()
    ner_extractor = ner_extractor or LangExtractNerExtractor()

    def task(*, item, **kwargs) -> dict:
        source_file = item.input["source_file"]
        field_keys = item.input["field_keys"]
        fields = [fields_by_key[key] for key in field_keys]

        start = time.perf_counter()
        pdf_bytes = (data_test_dir / source_file).read_bytes()
        text = pdf_extractor.extract_text(pdf_bytes)
        results = ner_extractor.extract(text, fields, source_filename=source_file)
        latency_seconds = time.perf_counter() - start

        return {
            "extraction_results": [result.model_dump() for result in results],
            "latency_seconds": latency_seconds,
            "ocr_page_count": len(getattr(pdf_extractor, "last_pages_ocr", [])),
        }

    return task


def build_field_evaluator(fields_by_key: dict[str, Field]):
    """Évaluateur item-level : compare `output` (résultats d'extraction du
    pipeline réel, indexés par `field_title`) à `expected_output` (annotations
    gold, indexées par `field_key`) pour chaque champ demandé, et renvoie un
    score TP/FP/FN/TN par champ (`match:{field_key}`) + un exact-match
    document (`exact_match`) + le statut `human_validation` du document
    (voir metadata posée par `gold_dataset_sync.sync_gold_dataset`), pour que
    l'évaluateur run-level (Task 6) puisse exclure les documents non validés
    des métriques principales sans requête supplémentaire.

    `typed_value` préféré à `value` pour la comparaison — c'est la valeur
    déjà nettoyée par le pipeline (voir `app/tools/ner_langextract.py`),
    plus proche de ce que le gold encode que le texte groundé brut."""
    from langfuse.experiment import Evaluation

    title_to_key = {field.title: field.key for field in fields_by_key.values()}

    def field_evaluator(
        *, output=None, expected_output=None, metadata=None, **kwargs
    ) -> list[Evaluation]:
        extraction_results = (output or {}).get("extraction_results", [])
        output_by_key = {
            title_to_key[result["field_title"]]: result
            for result in extraction_results
            if result["field_title"] in title_to_key
        }

        evaluations: list[Evaluation] = []
        exact_match = True
        for field_key, annotation in (expected_output or {}).items():
            field = fields_by_key.get(field_key)
            if field is None:
                continue

            extracted = output_by_key.get(field_key) or {}
            outcomes = classify_field(
                field_key=field_key,
                field_type=field.type,
                gold_value=annotation.get("value"),
                gold_page=(annotation.get("evidence") or {}).get("page"),
                extracted_value=extracted.get("typed_value") or extracted.get("value"),
                extracted_page=extracted.get("page_number"),
            )
            for outcome in outcomes:
                if outcome.kind not in ("tp", "tn"):
                    exact_match = False
                evaluations.append(
                    Evaluation(
                        name=f"match:{field_key}",
                        value=outcome.kind,
                        metadata={"grounding_match": outcome.grounding_match},
                    )
                )

        evaluations.append(Evaluation(name="exact_match", value=exact_match))
        evaluations.append(
            Evaluation(
                name="human_validation",
                value=bool((metadata or {}).get("human_validation")),
            )
        )
        return evaluations

    return field_evaluator


def _item_evaluation_value(item_result: Any, name: str) -> Any:
    for evaluation in item_result.evaluations:
        if evaluation.name == name:
            return evaluation.value
    return None


def _match_evaluations(item_result: Any) -> list[Any]:
    return [ev for ev in item_result.evaluations if ev.name.startswith("match:")]


def _precision_recall_f1(
    tp: int, fp: int, fn: int
) -> tuple[float | None, float | None, float | None]:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )
    return precision, recall, f1


def _field_metrics_evaluations(item_results: list[Any]) -> list[Any]:
    """P/R/F1 par champ (pool TP/FP/FN sur tous les documents validés) +
    macro (moyenne des F1 par champ) et micro (TP/FP/FN totaux, tous champs
    confondus) — voir Architecture Decisions du plan pour la convention
    TP/FP/FN (une valeur erronée compte pour 1 FP + 1 FN)."""
    from langfuse.experiment import Evaluation

    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    for item_result in item_results:
        for ev in _match_evaluations(item_result):
            field_key = ev.name.removeprefix("match:")
            counts[field_key][ev.value] += 1

    evaluations = []
    field_f1s = []
    total_tp = total_fp = total_fn = 0
    for field_key, c in counts.items():
        precision, recall, f1 = _precision_recall_f1(c["tp"], c["fp"], c["fn"])
        evaluations.append(
            Evaluation(
                name=f"precision:{field_key}",
                value=precision if precision is not None else 0.0,
                metadata=dict(c),
            )
        )
        evaluations.append(
            Evaluation(name=f"recall:{field_key}", value=recall if recall is not None else 0.0)
        )
        evaluations.append(
            Evaluation(name=f"f1:{field_key}", value=f1 if f1 is not None else 0.0)
        )
        if f1 is not None:
            field_f1s.append(f1)
        total_tp += c["tp"]
        total_fp += c["fp"]
        total_fn += c["fn"]

    macro_f1 = sum(field_f1s) / len(field_f1s) if field_f1s else 0.0
    micro_precision, micro_recall, micro_f1 = _precision_recall_f1(total_tp, total_fp, total_fn)

    evaluations.append(Evaluation(name="f1_macro", value=macro_f1))
    evaluations.append(Evaluation(name="precision_micro", value=micro_precision or 0.0))
    evaluations.append(Evaluation(name="recall_micro", value=micro_recall or 0.0))
    evaluations.append(Evaluation(name="f1_micro", value=micro_f1 or 0.0))
    return evaluations


def _exact_match_accuracy(item_results: list[Any]) -> Any:
    from langfuse.experiment import Evaluation

    if not item_results:
        return Evaluation(name="exact_match_accuracy", value=0.0)
    matches = sum(1 for r in item_results if _item_evaluation_value(r, "exact_match") is True)
    return Evaluation(name="exact_match_accuracy", value=matches / len(item_results))


def _grounding_accuracy(item_results: list[Any]) -> Any:
    """Part des valeurs correctement extraites (TP) dont la page rapportée
    correspond à la page gold — uniquement sur les TP où le gold renseigne
    une page (`evidence.page` non nul), voir `classify_field`."""
    from langfuse.experiment import Evaluation

    grounded = correct = 0
    for item_result in item_results:
        for ev in _match_evaluations(item_result):
            if ev.value != "tp":
                continue
            grounding_match = (ev.metadata or {}).get("grounding_match")
            if grounding_match is not None:
                grounded += 1
                if grounding_match:
                    correct += 1

    return Evaluation(
        name="grounding_accuracy",
        value=(correct / grounded) if grounded else 0.0,
        comment=(
            f"{correct}/{grounded} valeurs correctes avec la bonne page"
            if grounded
            else "aucune valeur correcte avec une page gold renseignée"
        ),
    )


def _percentile(sorted_values: list[float], p: int) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, round(p / 100 * (len(sorted_values) - 1)))
    return sorted_values[index]


def _latency_evaluations(item_results: list[Any]) -> list[Any]:
    from langfuse.experiment import Evaluation

    latencies = sorted(
        r.output["latency_seconds"]
        for r in item_results
        if isinstance(r.output, dict) and "latency_seconds" in r.output
    )
    if not latencies:
        return []
    return [
        Evaluation(name="latency_p50_seconds", value=_percentile(latencies, 50)),
        Evaluation(name="latency_p95_seconds", value=_percentile(latencies, 95)),
    ]


def _ocr_split_evaluations(item_results: list[Any]) -> list[Any]:
    from langfuse.experiment import Evaluation

    def _has_ocr(r: Any) -> bool:
        return isinstance(r.output, dict) and r.output.get("ocr_page_count", 0) > 0

    def _avg_latency(results: list[Any]) -> float:
        values = [
            r.output.get("latency_seconds")
            for r in results
            if isinstance(r.output, dict) and r.output.get("latency_seconds") is not None
        ]
        return sum(values) / len(values) if values else 0.0

    with_ocr = [r for r in item_results if _has_ocr(r)]
    without_ocr = [r for r in item_results if not _has_ocr(r)]
    return [
        Evaluation(name="documents_with_ocr", value=len(with_ocr)),
        Evaluation(name="documents_without_ocr", value=len(without_ocr)),
        Evaluation(name="latency_avg_seconds_with_ocr", value=_avg_latency(with_ocr)),
        Evaluation(name="latency_avg_seconds_without_ocr", value=_avg_latency(without_ocr)),
    ]


def build_run_evaluator():
    """Évaluateur run-level : agrège les `Evaluation` item-level
    (`build_field_evaluator`) en scores globaux. Les documents
    `human_validation: false` sont exclus des métriques "principales"
    (décision utilisateur, docs/ideas/ci-eval-gold-dataset.md) mais comptés
    à part (`documents_excluded_unvalidated`) — le Dataset Langfuse, lui,
    contient toujours tous les documents (sync sans filtrage, voir
    gold_dataset_sync.py).

    `cost_usd_total` posé à 0.0 avec un commentaire explicite plutôt
    qu'omis : LangExtract n'expose aucune info d'usage token dans son objet
    de retour (gap déjà documenté, tasks/todo-langfuse-tracing.md Task 6),
    donc `trace_llm_call` (app/tools/langfuse_tracer.py) ne pose jamais
    `usage_details`/`cost_details` sur ses generations — Langfuse ne peut
    donc rien calculer, avec ou sans requête API supplémentaire ici."""
    from langfuse.experiment import Evaluation

    def run_evaluator(*, item_results, **kwargs) -> list[Any]:
        validated = [
            r for r in item_results if _item_evaluation_value(r, "human_validation") is True
        ]

        evaluations = [
            Evaluation(name="documents_evaluated", value=len(validated)),
            Evaluation(
                name="documents_excluded_unvalidated",
                value=len(item_results) - len(validated),
            ),
        ]
        evaluations.extend(_field_metrics_evaluations(validated))
        evaluations.append(_exact_match_accuracy(validated))
        evaluations.append(_grounding_accuracy(validated))
        evaluations.extend(_latency_evaluations(validated))
        evaluations.extend(_ocr_split_evaluations(validated))
        evaluations.append(
            Evaluation(
                name="cost_usd_total",
                value=0.0,
                comment=(
                    "Non mesurable avec l'instrumentation actuelle : LangExtract "
                    "n'expose aucune info d'usage token, donc aucune generation "
                    "Langfuse ne porte usage_details/cost_details — voir "
                    "tasks/todo-langfuse-tracing.md (Task 6, gap déjà documenté)."
                ),
            )
        )
        return evaluations

    return run_evaluator


def run_eval(client: Any = None, *, max_concurrency: int = 3):
    """Rejoue le pipeline réel sur les 14 items du Dataset Langfuse
    `gold-devis` (déjà synchronisé par `gold_dataset_sync.py`) via
    `dataset.run_experiment`. `max_concurrency` volontairement bas par
    défaut : OCR (RapidOCR) est coûteux en mémoire/CPU par document
    (~2 min sur un PDF de 12 pages, voir choix_techniques.md) et les appels
    Gemini sont soumis à des limites de débit — pas de bénéfice à paralléliser
    largement 14 documents."""
    if client is None:
        from langfuse import Langfuse

        client = Langfuse()

    fields_by_key = {field.key: field for field in load_gold_fields()}
    dataset = client.get_dataset(DATASET_NAME)
    task = build_task(fields_by_key)

    return dataset.run_experiment(
        name="gold-devis-eval",
        task=task,
        evaluators=[build_field_evaluator(fields_by_key)],
        run_evaluators=[build_run_evaluator()],
        max_concurrency=max_concurrency,
    )


def main() -> None:
    load_env()
    result = run_eval()
    print(result.format())


if __name__ == "__main__":
    main()
