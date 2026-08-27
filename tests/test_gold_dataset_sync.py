from scripts.gold_dataset_sync import DATASET_NAME, sync_gold_dataset


class _FakeLangfuseClient:
    def __init__(self):
        self.created_datasets: list[dict] = []
        self.items: dict[str, dict] = {}

    def create_dataset(self, *, name, description=None, **kwargs):
        self.created_datasets.append({"name": name, "description": description})

    def create_dataset_item(self, *, dataset_name, id, input, expected_output, metadata):
        # Même sémantique que le SDK réel : create_dataset_item "upserts if
        # an item with id already exists" — un id déjà vu écrase l'entrée.
        self.items[id] = {
            "dataset_name": dataset_name,
            "input": input,
            "expected_output": expected_output,
            "metadata": metadata,
        }


def _write_gold_yaml(tmp_path, documents):
    import yaml

    path = tmp_path / "gold.yaml"
    path.write_text(yaml.safe_dump({"dataset": documents}), encoding="utf-8")
    return path


def test_sync_creates_the_dataset(tmp_path):
    client = _FakeLangfuseClient()
    yaml_path = _write_gold_yaml(tmp_path, [])

    sync_gold_dataset(client, yaml_path)

    assert client.created_datasets == [
        {
            "name": DATASET_NAME,
            "description": "Dataset gold devis — voir specs/ci-eval-gold-dataset.md",
        }
    ]


def test_sync_upserts_one_item_per_document(tmp_path):
    client = _FakeLangfuseClient()
    yaml_path = _write_gold_yaml(
        tmp_path,
        [
            {
                "document_id": 1,
                "source_file": "devis.pdf",
                "human_validation": True,
                "annotations": {
                    "numero_devis": {"value": "42", "evidence": {"text": None, "page": 1}}
                },
            }
        ],
    )

    count = sync_gold_dataset(client, yaml_path)

    assert count == 1
    item = client.items["gold-devis-1"]
    assert item["dataset_name"] == DATASET_NAME
    assert item["input"] == {"source_file": "devis.pdf", "field_keys": ["numero_devis"]}
    assert item["expected_output"] == {
        "numero_devis": {"value": "42", "evidence": {"text": None, "page": 1}}
    }
    assert item["metadata"] == {"document_id": 1, "human_validation": True}


def test_sync_is_idempotent_no_duplicate_items(tmp_path):
    client = _FakeLangfuseClient()
    yaml_path = _write_gold_yaml(
        tmp_path,
        [
            {
                "document_id": 1,
                "source_file": "devis.pdf",
                "human_validation": True,
                "annotations": {},
            }
        ],
    )

    sync_gold_dataset(client, yaml_path)
    sync_gold_dataset(client, yaml_path)

    assert len(client.items) == 1
    assert len(client.created_datasets) == 2  # create_dataset ré-appelé, idempotent côté SDK réel


def test_sync_rerun_updates_a_changed_document(tmp_path):
    client = _FakeLangfuseClient()
    yaml_path = _write_gold_yaml(
        tmp_path,
        [
            {
                "document_id": 1,
                "source_file": "devis.pdf",
                "human_validation": False,
                "annotations": {},
            }
        ],
    )
    sync_gold_dataset(client, yaml_path)

    yaml_path.write_text(
        __import__("yaml").safe_dump(
            {
                "dataset": [
                    {
                        "document_id": 1,
                        "source_file": "devis.pdf",
                        "human_validation": True,
                        "annotations": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sync_gold_dataset(client, yaml_path)

    assert len(client.items) == 1
    assert client.items["gold-devis-1"]["metadata"]["human_validation"] is True
