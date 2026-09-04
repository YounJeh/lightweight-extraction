from types import SimpleNamespace

from langfuse.experiment import Evaluation

from app.models import Field
from scripts.gold_dataset_eval import DATA_TEST_DIR
from scripts.nuextract_train_langfuse_eval import (
    TRAIN_DATA_DIR,
    _evidence_similarity_evaluations,
    _run_name,
    build_evidence_similarity_evaluator,
    build_run_evaluator,
    run_eval,
)

_NUMERO_DEVIS = Field(
    id=1, key="numero_devis", title="Numéro de devis", definition="d", type="text"
)


def test_train_data_dir_is_the_train_subfolder_of_data_test():
    assert TRAIN_DATA_DIR == DATA_TEST_DIR / "train"


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
    assert by_name["latency_p50_seconds"].value == 20.0


def test_run_evaluator_has_no_ocr_split_evaluations():
    run_evaluator = build_run_evaluator()

    evaluations = run_evaluator(item_results=[])

    names = {ev.name for ev in evaluations}
    assert "documents_with_ocr" not in names
    assert "documents_without_ocr" not in names


def test_run_name_sanitizes_slashes_in_the_model_id():
    assert _run_name("numind/NuExtract3") == "train-devis-nuextract-numind_NuExtract3"


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

    assert fake_client.received_dataset_name == "train-devis"
    kwargs = fake_client.dataset.received_kwargs
    assert kwargs["name"] == "train-devis-nuextract-numind_NuExtract3"
    assert kwargs["max_concurrency"] == 14
    assert callable(kwargs["task"])
    assert len(kwargs["evaluators"]) == 2
    assert len(kwargs["run_evaluators"]) == 1
    assert result == "sentinel-result"


def test_evidence_similarity_evaluator_scores_one_for_an_identical_evidence():
    evaluator = build_evidence_similarity_evaluator({"numero_devis": _NUMERO_DEVIS})

    evaluations = evaluator(
        output={
            "extraction_results": [
                {"field_title": "Numéro de devis", "evidence": "Devis N° DE00020090"}
            ]
        },
        expected_output={
            "numero_devis": {
                "value": "DE00020090",
                "evidence": {"text": "Devis N° DE00020090", "page": 1},
            }
        },
    )

    assert len(evaluations) == 1
    assert evaluations[0].name == "evidence_similarity:numero_devis"
    assert evaluations[0].value == 1.0


def test_evidence_similarity_evaluator_scores_partial_match_between_zero_and_one():
    evaluator = build_evidence_similarity_evaluator({"numero_devis": _NUMERO_DEVIS})

    evaluations = evaluator(
        output={
            "extraction_results": [
                {"field_title": "Numéro de devis", "evidence": "DE00020090"}
            ]
        },
        expected_output={
            "numero_devis": {
                "value": "DE00020090",
                "evidence": {"text": "Devis N° DE00020090, daté du 12 mars", "page": 1},
            }
        },
    )

    assert 0.0 < evaluations[0].value < 1.0


def test_evidence_similarity_evaluator_emits_nothing_when_gold_has_no_evidence_text():
    evaluator = build_evidence_similarity_evaluator({"numero_devis": _NUMERO_DEVIS})

    evaluations = evaluator(
        output={"extraction_results": []},
        expected_output={"numero_devis": {"value": "DE00020090", "evidence": {"text": None}}},
    )

    assert evaluations == []


def test_evidence_similarity_evaluator_scores_zero_when_extraction_has_no_evidence():
    evaluator = build_evidence_similarity_evaluator({"numero_devis": _NUMERO_DEVIS})

    evaluations = evaluator(
        output={"extraction_results": [{"field_title": "Numéro de devis", "evidence": None}]},
        expected_output={
            "numero_devis": {"value": "DE00020090", "evidence": {"text": "Devis N° DE00020090"}}
        },
    )

    assert len(evaluations) == 1
    assert evaluations[0].name == "evidence_similarity:numero_devis"
    assert evaluations[0].value == 0.0


def test_evidence_similarity_evaluations_averages_scores_per_field_and_macro():
    items = [
        _item_result(
            evaluations=[
                Evaluation(name="evidence_similarity:numero_devis", value=1.0),
                Evaluation(name="evidence_similarity:nom_societe", value=0.5),
            ],
            output={},
        ),
        _item_result(
            evaluations=[Evaluation(name="evidence_similarity:numero_devis", value=0.0)],
            output={},
        ),
    ]

    evaluations = _evidence_similarity_evaluations(items)
    by_name = _evaluations_by_name(evaluations)

    assert by_name["evidence_similarity:numero_devis"].value == 0.5  # (1.0 + 0.0) / 2
    assert by_name["evidence_similarity:nom_societe"].value == 0.5
    assert by_name["evidence_similarity_macro"].value == 0.5  # moyenne de (0.5, 0.5)


def test_evidence_similarity_evaluations_omits_macro_when_no_score_at_all():
    evaluations = _evidence_similarity_evaluations(
        [_item_result(evaluations=[Evaluation(name="human_validation", value=True)], output={})]
    )

    assert evaluations == []


def test_run_eval_reads_pdfs_from_the_train_subfolder(monkeypatch, tmp_path):
    captured: dict = {}

    def _fake_build_task(fields_by_key, *, data_test_dir, extractor=None):
        captured["data_test_dir"] = data_test_dir
        return lambda *, item, **kwargs: {}

    monkeypatch.setattr(
        "scripts.nuextract_train_langfuse_eval.build_task", _fake_build_task
    )
    fake_client = _FakeLangfuseClient()

    run_eval(fake_client)

    assert captured["data_test_dir"] == TRAIN_DATA_DIR
