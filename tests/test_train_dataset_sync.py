from scripts.train_dataset_sync import DATASET_NAME, sync_train_dataset


class _FakeLangfuseClient:
    def __init__(self):
        self.created_datasets: list[dict] = []
        self.items: dict[str, dict] = {}

    def create_dataset(self, *, name, description=None, **kwargs):
        self.created_datasets.append({"name": name, "description": description})

    def create_dataset_item(self, *, dataset_name, id, input, expected_output, metadata):
        self.items[id] = {
            "dataset_name": dataset_name,
            "input": input,
            "expected_output": expected_output,
            "metadata": metadata,
        }


def _write_yaml(path, documents):
    import yaml

    path.write_text(yaml.safe_dump({"dataset": documents}), encoding="utf-8")
    return path


def _document(document_id, source_file="devis.pdf", human_validation=True, annotations=None):
    return {
        "document_id": document_id,
        "source_file": source_file,
        "human_validation": human_validation,
        "annotations": annotations or {},
    }


def test_sync_creates_the_dataset(tmp_path):
    client = _FakeLangfuseClient()

    sync_train_dataset(client, tmp_path)

    assert client.created_datasets == [
        {
            "name": DATASET_NAME,
            "description": (
                "Dataset train devis (annotation web) — voir "
                "tasks/plan-nuextract-train-eval.md"
            ),
        }
    ]


def test_sync_upserts_one_item_per_document_across_yaml_files(tmp_path):
    client = _FakeLangfuseClient()
    _write_yaml(
        tmp_path / "web_documents_2026-09-02.yaml",
        [
            _document(
                1,
                source_file="a.pdf",
                annotations={
                    "numero_devis": {"value": "42", "evidence": {"text": None, "page": 1}}
                },
            )
        ],
    )
    _write_yaml(tmp_path / "web_documents_2026-09-03.yaml", [_document(1, source_file="b.pdf")])

    count = sync_train_dataset(client, tmp_path)

    assert count == 2
    item_a = client.items["train-devis-web_documents_2026-09-02-1"]
    assert item_a["dataset_name"] == DATASET_NAME
    assert item_a["input"] == {"source_file": "a.pdf", "field_keys": ["numero_devis"]}
    assert item_a["expected_output"] == {
        "numero_devis": {"value": "42", "evidence": {"text": None, "page": 1}}
    }
    assert item_a["metadata"] == {"document_id": 1, "human_validation": True}
    item_b = client.items["train-devis-web_documents_2026-09-03-1"]
    assert item_b["input"]["source_file"] == "b.pdf"


def test_sync_does_not_collide_when_document_id_repeats_across_files(tmp_path):
    # Les document_id sont uniques *dans* un fichier mais pas *entre*
    # fichiers (annotés en plusieurs sessions) -- l'id Langfuse doit rester
    # unique malgré ça, voir tasks/plan-nuextract-train-eval.md.
    client = _FakeLangfuseClient()
    _write_yaml(tmp_path / "web_documents_2026-09-02.yaml", [_document(20, source_file="a.pdf")])
    _write_yaml(tmp_path / "web_documents_2026-09-04.yaml", [_document(20, source_file="c.pdf")])

    count = sync_train_dataset(client, tmp_path)

    assert count == 2
    assert len(client.items) == 2
    assert client.items["train-devis-web_documents_2026-09-02-20"]["input"]["source_file"] == "a.pdf"
    assert client.items["train-devis-web_documents_2026-09-04-20"]["input"]["source_file"] == "c.pdf"


def test_sync_is_idempotent_no_duplicate_items(tmp_path):
    client = _FakeLangfuseClient()
    _write_yaml(tmp_path / "web_documents_2026-09-02.yaml", [_document(1)])

    sync_train_dataset(client, tmp_path)
    sync_train_dataset(client, tmp_path)

    assert len(client.items) == 1
    assert len(client.created_datasets) == 2  # create_dataset ré-appelé, idempotent côté SDK réel


def test_sync_only_reads_web_documents_yaml_files(tmp_path):
    client = _FakeLangfuseClient()
    _write_yaml(tmp_path / "web_documents_2026-09-02.yaml", [_document(1)])
    (tmp_path / "notes.txt").write_text("pas un dataset", encoding="utf-8")

    count = sync_train_dataset(client, tmp_path)

    assert count == 1
