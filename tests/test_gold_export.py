import yaml

from app.gold_export import GoldExportError, export_to_gold


def _write_yaml(path, documents):
    path.write_text(
        yaml.safe_dump({"dataset": documents}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _read_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_export_new_source_file_appends_document_with_next_id(tmp_path):
    yaml_path = tmp_path / "gold.yaml"
    _write_yaml(
        yaml_path,
        [
            {
                "document_id": 1,
                "source_file": "a.pdf",
                "human_validation": True,
                "annotations": {"numero_devis": {"value": "1", "evidence": {"text": None, "page": None}}},
            },
            {
                "document_id": 2,
                "source_file": "b.pdf",
                "human_validation": True,
                "annotations": {},
            },
        ],
    )

    result = export_to_gold(
        yaml_path,
        source_file="c.pdf",
        annotations={
            "numero_devis": {"value": "42", "evidence": {"text": None, "page": None}},
        },
    )

    assert result.document_id == 3
    assert result.created is True
    assert result.field_keys == ["numero_devis"]

    data = _read_yaml(yaml_path)
    new_doc = next(d for d in data["dataset"] if d["source_file"] == "c.pdf")
    assert new_doc["document_id"] == 3
    assert new_doc["human_validation"] is True
    assert new_doc["annotations"] == {
        "numero_devis": {"value": "42", "evidence": {"text": None, "page": None}}
    }
    # les documents existants ne sont pas altérés
    assert len(data["dataset"]) == 3


def test_export_existing_source_file_merges_annotations(tmp_path):
    yaml_path = tmp_path / "gold.yaml"
    _write_yaml(
        yaml_path,
        [
            {
                "document_id": 1,
                "source_file": "a.pdf",
                "human_validation": True,
                "annotations": {
                    "numero_devis": {"value": "1", "evidence": {"text": None, "page": None}},
                    "nom_societe": {"value": "ACME", "evidence": {"text": None, "page": None}},
                },
            }
        ],
    )

    result = export_to_gold(
        yaml_path,
        source_file="a.pdf",
        annotations={
            "nom_societe": {"value": "ACME CORP", "evidence": {"text": None, "page": None}},
            "pourcentage_acompte": {"value": "30", "evidence": {"text": None, "page": None}},
        },
    )

    assert result.document_id == 1
    assert result.created is False

    data = _read_yaml(yaml_path)
    assert len(data["dataset"]) == 1
    annotations = data["dataset"][0]["annotations"]
    # champ non re-coché cette fois -> inchangé
    assert annotations["numero_devis"] == {"value": "1", "evidence": {"text": None, "page": None}}
    # champ re-coché -> écrasé
    assert annotations["nom_societe"]["value"] == "ACME CORP"
    # nouveau champ coché -> ajouté
    assert annotations["pourcentage_acompte"]["value"] == "30"


def test_export_empty_annotations_raises_and_does_not_write(tmp_path):
    yaml_path = tmp_path / "gold.yaml"
    _write_yaml(
        yaml_path,
        [{"document_id": 1, "source_file": "a.pdf", "human_validation": True, "annotations": {}}],
    )
    original = yaml_path.read_text(encoding="utf-8")

    try:
        export_to_gold(yaml_path, source_file="a.pdf", annotations={})
        assert False, "GoldExportError attendue"
    except GoldExportError:
        pass

    assert yaml_path.read_text(encoding="utf-8") == original


def test_export_none_value_round_trips_as_yaml_null(tmp_path):
    yaml_path = tmp_path / "gold.yaml"
    _write_yaml(yaml_path, [])

    export_to_gold(
        yaml_path,
        source_file="a.pdf",
        annotations={
            "numero_devis": {"value": None, "evidence": {"text": None, "page": None}},
        },
    )

    data = _read_yaml(yaml_path)
    assert data["dataset"][0]["annotations"]["numero_devis"]["value"] is None


def test_export_to_missing_file_creates_first_document(tmp_path):
    yaml_path = tmp_path / "gold.yaml"

    result = export_to_gold(
        yaml_path,
        source_file="a.pdf",
        annotations={"numero_devis": {"value": "1", "evidence": {"text": None, "page": None}}},
    )

    assert result.document_id == 1
    assert result.created is True
    data = _read_yaml(yaml_path)
    assert len(data["dataset"]) == 1
