from types import SimpleNamespace

from langfuse.experiment import Evaluation

from app.models import ExtractionResult, Field
from scripts.nuextract_gold_langfuse_eval import (
    _run_name,
    build_run_evaluator,
    build_task,
    run_eval,
)

_NUMERO_DEVIS = Field(
    id=1, key="numero_devis", title="Numéro de devis", definition="d", type="text"
)


class _FakeExtractor:
    def __init__(
        self, results: list[ExtractionResult], *, retry_delays: list[float] | None = None
    ):
        self.results = results
        self.received: dict | None = None
        self._retry_delays = retry_delays or []

    def __call__(
        self, pdf_bytes: bytes, fields: list[Field], *, on_retry=None, **kwargs
    ) -> list[ExtractionResult]:
        self.received = {"pdf_bytes": pdf_bytes, "fields": fields}
        if on_retry is not None:
            for delay in self._retry_delays:
                on_retry(delay)
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
            "evidence": None,
            "source": "nuextract",
            "page_number": None,
            "text_position": None,
            "value_type": None,
            "typed_value": "n°6952",
            "type_error": None,
        }
    ]
    assert output["latency_seconds"] >= 0
    assert output["cold_start_seconds"] == 0.0  # aucun retry simulé ici


def test_build_task_accumulates_cold_start_seconds_from_on_retry(tmp_path):
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake-bytes")
    extractor = _FakeExtractor([], retry_delays=[5.0, 10.0, 20.0])

    task = build_task(
        {"numero_devis": _NUMERO_DEVIS}, extractor=extractor, data_test_dir=tmp_path
    )
    item = SimpleNamespace(input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]})

    output = task(item=item)

    assert output["cold_start_seconds"] == 35.0


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


def test_run_evaluator_computes_extraction_latency_net_of_cold_start():
    items = [
        _item_result(
            evaluations=[Evaluation(name="human_validation", value=True)],
            output={
                "extraction_results": [],
                "latency_seconds": total,
                "cold_start_seconds": cold_start,
            },
        )
        for total, cold_start in [(10.0, 8.0), (20.0, 15.0), (30.0, 25.0)]
    ]
    # latences nettoyées : 2.0, 5.0, 5.0

    run_evaluator = build_run_evaluator()
    evaluations = run_evaluator(item_results=items)
    by_name = _evaluations_by_name(evaluations)

    assert by_name["extraction_latency_p50_seconds"].value == 5.0
    # latence brute (inchangée, cold-start inclus) toujours présente aussi
    assert by_name["latency_p50_seconds"].value == 20.0


def test_run_evaluator_extraction_latency_defaults_to_zero_cold_start():
    items = [
        _item_result(
            evaluations=[Evaluation(name="human_validation", value=True)],
            output={"extraction_results": [], "latency_seconds": 7.0},  # pas de cold_start_seconds
        )
    ]

    run_evaluator = build_run_evaluator()
    evaluations = run_evaluator(item_results=items)
    by_name = _evaluations_by_name(evaluations)

    assert by_name["extraction_latency_p50_seconds"].value == 7.0


def test_run_evaluator_has_no_ocr_split_evaluations():
    run_evaluator = build_run_evaluator()

    evaluations = run_evaluator(item_results=[])

    names = {ev.name for ev in evaluations}
    assert "documents_with_ocr" not in names
    assert "documents_without_ocr" not in names


def test_run_name_sanitizes_slashes_in_the_model_id():
    assert _run_name("numind/NuExtract3") == "gold-devis-nuextract-numind_NuExtract3"


class _FakeDataset:
    def __init__(self):
        self.received_kwargs: dict | None = None

    def run_experiment(self, **kwargs):
        self.received_kwargs = kwargs
        return "sentinel-result"


class _FakeLangfuseClient:
    def __init__(self):
        self.dataset = _FakeDataset()
        self.received_dataset_name: str | None = None

    def get_dataset(self, name: str):
        self.received_dataset_name = name
        return self.dataset


def test_run_eval_wires_the_dataset_run_experiment_call():
    fake_client = _FakeLangfuseClient()

    result = run_eval(fake_client, max_concurrency=14, model="numind/NuExtract3")

    assert fake_client.received_dataset_name == "gold-devis"
    kwargs = fake_client.dataset.received_kwargs
    assert kwargs["name"] == "gold-devis-nuextract-numind_NuExtract3"
    assert kwargs["max_concurrency"] == 14
    assert callable(kwargs["task"])
    assert len(kwargs["evaluators"]) == 1
    assert len(kwargs["run_evaluators"]) == 1
    assert result == "sentinel-result"
