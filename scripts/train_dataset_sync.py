"""Synchronise les YAML tests/data/train/web_documents_*.yaml vers le
Dataset Langfuse "train-devis" (upsert par item id) — un fichier par
session d'annotation web, fusionnés en un seul dataset. Même contrat que
`gold_dataset_sync.py` (import direct, jamais modifié).

Voir tasks/plan-nuextract-train-eval.md pour le contexte complet.
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.config import load_env  # noqa: E402

DATASET_NAME = "train-devis"
TRAIN_YAML_DIR = Path(__file__).resolve().parent.parent / "tests" / "data" / "train"


def _load_train_documents(yaml_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """Renvoie une liste de `(yaml_stem, document)`, un par document de
    chaque `web_documents_*.yaml` du dossier — fichiers parcourus triés par
    nom pour un ordre déterministe. `yaml_stem` sert de préfixe d'id
    (`sync_train_dataset`) : les `document_id` sont uniques à l'intérieur
    d'un fichier mais se chevauchent entre fichiers (annotations faites en
    plusieurs sessions), donc l'id seul ne suffit pas à identifier un item
    Langfuse de façon globalement unique."""
    documents = []
    for yaml_path in sorted(yaml_dir.glob("web_documents_*.yaml")):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        for doc in data["dataset"]:
            documents.append((yaml_path.stem, doc))
    return documents


def sync_train_dataset(client: Any, yaml_dir: Path = TRAIN_YAML_DIR) -> int:
    """Crée le Dataset `train-devis` s'il n'existe pas encore, puis upsert
    un item par document de chaque YAML train (id stable
    `train-devis-{yaml_stem}-{document_id}`, voir `_load_train_documents`).
    Idempotent : relancer ce script ne duplique jamais les items. Retourne
    le nombre de documents synchronisés."""
    client.create_dataset(
        name=DATASET_NAME,
        description=(
            "Dataset train devis (annotation web) — voir "
            "tasks/plan-nuextract-train-eval.md"
        ),
    )

    documents = _load_train_documents(yaml_dir)
    for yaml_stem, doc in documents:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=f"{DATASET_NAME}-{yaml_stem}-{doc['document_id']}",
            input={
                "source_file": doc["source_file"],
                "field_keys": sorted(doc["annotations"].keys()),
            },
            expected_output=doc["annotations"],
            metadata={
                "document_id": doc["document_id"],
                "human_validation": doc["human_validation"],
            },
        )
    return len(documents)


def main() -> None:
    load_env()
    from langfuse import Langfuse

    count = sync_train_dataset(Langfuse())
    print(f"Dataset '{DATASET_NAME}' synchronisé : {count} documents.")


if __name__ == "__main__":
    main()
