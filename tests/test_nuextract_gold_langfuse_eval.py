from types import SimpleNamespace

from langfuse.experiment import Evaluation

from app.models import ExtractionResult, Field
from scripts.nuextract_gold_langfuse_eval import build_run_evaluator, build_task

_NUMERO_DEVIS = Field(
    id=1, key="numero_devis", title="Numéro de devis", definition="d", type="text"
)


class _FakeExtractor:
    def __init__(self, results: list[ExtractionResult]):
        self.results = results
        self.received: dict | None = None

    def __call__(self, pdf_bytes: bytes, fields: list[Field]) -> list[ExtractionResult]:
        self.received = {"pdf_bytes": pdf_bytes, "fields": fields}
        return self.results


def test_build_task_reads_the_referenced_pdf_and_extracts_selected_fields(tmp_path):
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake-bytes")
    extractor = _FakeExtractor(
        [
            ExtractionResult(
                field_title="Numéro de devis", value="n°6952", source="nuextract", typed_value="n°6952"
            )
        ]
    )

    task = build_task(
        {"numero_devis": _NUMERO_DEVIS}, extractor=extractor, data_test_dir=tmp_path
    )
    item = SimpleNamespace(input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]})

    output = task(item=item)

    assert extractor.received == {"pdf_bytes": b"%PDF-fake-bytes", "fields": [_NUMERO_DEVIS]}
    assert output["extraction_results"] == [
        {
            "field_title": "Numéro de devis",
            "value": "n°6952",
            "source": "nuextract",
            "page_number": None,
            "text_position": None,
            "value_type": None,
            "typed_value": "n°6952",
            "type_error": None,
        }
    ]
    assert output["latency_seconds"] >= 0


def test_build_task_resolves_only_the_fields_listed_for_this_item(tmp_path):
    other = Field(id=2, key="nom_societe", title="Nom de la société", definition="d", type="text")
    (tmp_path / "devis.pdf").write_bytes(b"%PDF")
    extractor = _FakeExtractor([])

    task = build_task(
        {"numero_devis": _NUMERO_DEVIS, "nom_societe": other},
        extractor=extractor,
        data_test_dir=tmp_path,
    )
    item = SimpleNamespace(input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]})

    task(item=item)

    assert extractor.received["fields"] == [_NUMERO_DEVIS]


def _item_result(*, evaluations, output):
    return SimpleNamespace(evaluations=evaluations, output=output)


def _evaluations_by_name(evaluations):
    return {ev.name: ev for ev in evaluations}


def test_run_evaluator_excludes_unvalidated_documents_from_main_metrics():
    validated_tp = _item_result(
        evaluations=[
            Evaluation(name="match:numero_devis", value="tp", metadata={"grounding_match": None}),
            Evaluation(name="exact_match", value=True),
            Evaluation(name="human_validation", value=True),
        ],
        output={"extraction_results": [], "latency_seconds": 2.0},
    )
    unvalidated_fn = _item_result(
        evaluations=[
            Evaluation(name="match:numero_devis", value="fn"),
            Evaluation(name="exact_match", value=False),
            Evaluation(name="human_validation", value=False),
        ],
        output={"extraction_results": [], "latency_seconds": 99.0},
    )

    run_evaluator = build_run_evaluator()
    evaluations = run_evaluator(item_results=[validated_tp, unvalidated_fn])

    by_name = _evaluations_by_name(evaluations)
    assert by_name["documents_evaluated"].value == 1
    assert by_name["documents_excluded_unvalidated"].value == 1
    assert by_name["exact_match_accuracy"].value == 1.0
    # coût : uniquement le document validé (2.0s), pas les 99.0s de l'exclu
    assert by_name["cost_usd_total"].value == 2.0 / 3600 * 0.80


def test_run_evaluator_computes_macro_and_micro_f1():
    tp_item = _item_result(
        evaluations=[
            Evaluation(name="match:numero_devis", value="tp", metadata={"grounding_match": None}),
            Evaluation(name="exact_match", value=True),
            Evaluation(name="human_validation", value=True),
        ],
        output={"extraction_results": [], "latency_seconds": 1.0},
    )
    wrong_item = _item_result(
        evaluations=[
            Evaluation(name="match:numero_devis", value="fp"),
            Evaluation(name="match:numero_devis", value="fn"),
            Evaluation(name="exact_match", value=False),
            Evaluation(name="human_validation", value=True),
        ],
        output={"extraction_results": [], "latency_seconds": 3.0},
    )

    run_evaluator = build_run_evaluator()
    evaluations = run_evaluator(item_results=[tp_item, wrong_item])
    by_name = _evaluations_by_name(evaluations)

    # 1 tp, 1 fp, 1 fn -> precision=0.5, recall=0.5, f1=0.5
    assert by_name["precision:numero_devis"].value == 0.5
    assert by_name["recall:numero_devis"].value == 0.5
    assert by_name["f1:numero_devis"].value == 0.5


def test_run_evaluator_cost_sums_latency_across_items():
    items = [
        _item_result(
            evaluations=[Evaluation(name="human_validation", value=True)],
            output={"extraction_results": [], "latency_seconds": seconds},
        )
        for seconds in (10.0, 20.0, 30.0)
    ]

    run_evaluator = build_run_evaluator()
    evaluations = run_evaluator(item_results=items)
    by_name = _evaluations_by_name(evaluations)

    # (10 + 20 + 30) / 3600 * 0.80
    assert by_name["cost_usd_total"].value == 60.0 / 3600 * 0.80
    assert by_name["cost_usd_total"].comment  # explique l'approximation, pas un chiffre nu


def test_run_evaluator_has_no_ocr_split_evaluations():
    run_evaluator = build_run_evaluator()

    evaluations = run_evaluator(item_results=[])

    names = {ev.name for ev in evaluations}
    assert "documents_with_ocr" not in names
    assert "documents_without_ocr" not in names
