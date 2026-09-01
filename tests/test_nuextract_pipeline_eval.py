import yaml

from app.models import ExtractionResult, Field
from scripts.gold_dataset_eval import load_gold_fields
from scripts.nuextract_pipeline_eval import aggregate_scores, run, run_document, write_results_csv

_NUMERO_DEVIS = Field(
    id=1, key="numero_devis", title="Numéro de devis", definition="d", type="text"
)


def _fake_extractor(results_by_key: dict[str, str]):
    """Extracteur factice : renvoie, pour chaque `field` demandé, un
    `ExtractionResult` construit à partir de `results_by_key[field.key]`
    (ou une valeur vide si absent) — même forme que
    `nuextract_client.extract`, sans appel réseau."""

    def extractor(pdf_bytes: bytes, fields: list[Field]) -> list[ExtractionResult]:
        results = []
        for field in fields:
            value = results_by_key.get(field.key, "")
            results.append(
                ExtractionResult(
                    field_title=field.title,
                    value=value,
                    source="nuextract",
                    value_type=field.type,
                    typed_value=value or None,
                )
            )
        return results

    return extractor


def test_run_document_classifies_a_matching_field_as_true_positive(tmp_path):
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake")
    doc = {
        "document_id": 1,
        "source_file": "devis.pdf",
        "annotations": {"numero_devis": {"value": "n°6952", "evidence": {"page": 1, "text": None}}},
    }

    result = run_document(
        doc,
        {"numero_devis": _NUMERO_DEVIS},
        extractor=_fake_extractor({"numero_devis": "n°6952"}),
        data_test_dir=tmp_path,
    )

    assert [o.kind for o in result["outcomes"]] == ["tp"]
    assert result["rows"][0]["extracted_value"] == "n°6952"
    assert result["rows"][0]["match"] == "tp"


def test_run_document_classifies_a_wrong_value_as_fp_and_fn(tmp_path):
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake")
    doc = {
        "document_id": 1,
        "source_file": "devis.pdf",
        "annotations": {"numero_devis": {"value": "n°6952", "evidence": {"page": 1, "text": None}}},
    }

    result = run_document(
        doc,
        {"numero_devis": _NUMERO_DEVIS},
        extractor=_fake_extractor({"numero_devis": "AUTRE"}),
        data_test_dir=tmp_path,
    )

    assert {o.kind for o in result["outcomes"]} == {"fp", "fn"}


def test_run_document_reads_the_pdf_referenced_by_source_file(tmp_path):
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake")
    received: dict = {}

    def extractor(pdf_bytes, fields):
        received["pdf_bytes"] = pdf_bytes
        return [
            ExtractionResult(field_title=f.title, value="x", source="nuextract", typed_value="x")
            for f in fields
        ]

    doc = {
        "document_id": 1,
        "source_file": "devis.pdf",
        "annotations": {"numero_devis": {"value": "x", "evidence": {"page": None, "text": None}}},
    }

    run_document(doc, {"numero_devis": _NUMERO_DEVIS}, extractor=extractor, data_test_dir=tmp_path)

    assert received["pdf_bytes"] == b"%PDF-fake"


def test_aggregate_scores_pools_outcomes_across_documents():
    from scripts.gold_matching import FieldOutcome

    outcomes = [
        FieldOutcome("numero_devis", "tp"),
        FieldOutcome("numero_devis", "fp"),
        FieldOutcome("numero_devis", "fn"),
        FieldOutcome("nom_societe", "tp"),
    ]

    scores = aggregate_scores(outcomes)

    assert scores["numero_devis"]["precision"] == 0.5
    assert scores["numero_devis"]["recall"] == 0.5
    assert scores["nom_societe"]["f1"] == 1.0


def test_write_results_csv_creates_parent_dirs_and_a_header(tmp_path):
    output_path = tmp_path / "nested" / "results.csv"

    write_results_csv(
        [
            {
                "document_id": 1,
                "source_file": "devis.pdf",
                "field_key": "numero_devis",
                "gold_value": "n°6952",
                "extracted_value": "n°6952",
                "match": "tp",
                "latency_seconds": "1.23",
            }
        ],
        output_path,
    )

    content = output_path.read_text(encoding="utf-8")
    assert "document_id" in content.splitlines()[0]
    assert "n°6952" in content


def test_run_end_to_end_with_a_fake_extractor(tmp_path):
    gold_yaml_path = tmp_path / "gold.yaml"
    data_test_dir = tmp_path / "data_test"
    data_test_dir.mkdir()
    (data_test_dir / "devis.pdf").write_bytes(b"%PDF-fake")
    gold_yaml_path.write_text(
        yaml.safe_dump(
            {
                "dataset": [
                    {
                        "document_id": 1,
                        "source_file": "devis.pdf",
                        "human_validation": True,
                        "annotations": {
                            "numero_devis": {
                                "value": "n°6952",
                                "evidence": {"page": 1, "text": None},
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "results.csv"

    scores = run(
        extractor=_fake_extractor({"numero_devis": "n°6952"}),
        gold_yaml_path=gold_yaml_path,
        data_test_dir=data_test_dir,
        output_path=output_path,
    )

    assert scores["numero_devis"]["f1"] == 1.0
    assert output_path.exists()


def test_run_limit_restricts_to_the_first_n_documents(tmp_path):
    data_test_dir = tmp_path / "data_test"
    data_test_dir.mkdir()
    (data_test_dir / "devis1.pdf").write_bytes(b"%PDF-1")
    (data_test_dir / "devis2.pdf").write_bytes(b"%PDF-2")
    gold_yaml_path = tmp_path / "gold.yaml"
    gold_yaml_path.write_text(
        yaml.safe_dump(
            {
                "dataset": [
                    {
                        "document_id": i,
                        "source_file": f"devis{i}.pdf",
                        "human_validation": True,
                        "annotations": {
                            "numero_devis": {"value": "x", "evidence": {"page": None, "text": None}}
                        },
                    }
                    for i in (1, 2)
                ]
            }
        ),
        encoding="utf-8",
    )

    scores = run(
        extractor=_fake_extractor({"numero_devis": "x"}),
        gold_yaml_path=gold_yaml_path,
        data_test_dir=data_test_dir,
        output_path=tmp_path / "results.csv",
        limit=1,
    )

    # 1 seul document rejoué -> 1 tp, pas 2
    assert scores["numero_devis"]["tp"] == 1


def test_load_gold_fields_still_has_numero_devis_for_these_tests():
    # Sentinel : ces tests supposent que "numero_devis" existe dans le gold
    # réel (utilisé indirectement par run() via load_gold_fields()).
    assert "numero_devis" in {f.key for f in load_gold_fields()}
