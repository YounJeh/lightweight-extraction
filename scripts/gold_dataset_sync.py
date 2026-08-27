"""Synchronise tests/data/dataset_gold_devis.yaml vers le Dataset Langfuse
"gold-devis" (upsert par item id) — le YAML reste la seule source de vérité
éditable, le Dataset Langfuse est un miroir recalculé à chaque exécution.

Voir specs/ci-eval-gold-dataset.md pour le contexte complet.

API Langfuse vérifiée contre le SDK installé (langfuse==4.14.5) avant
d'écrire ce script (skill `langfuse`, principe "Documentation First") :
- `Langfuse.create_dataset(name=...)` est idempotent par nom (vérifié en
  réel : deux appels successifs renvoient le même id, pas de doublon).
- `Langfuse.create_dataset_item(dataset_name=..., id=..., ...)` "Upserts if
  an item with id already exists" (docstring du SDK) — l'id doit être
  globalement unique (pas seulement au sein du dataset), d'où le préfixe
  DATASET_NAME sur l'id.
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from app.config import load_env  # noqa: E402

DATASET_NAME = "gold-devis"
GOLD_YAML_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "data" / "dataset_gold_devis.yaml"
)


def _load_gold_documents(yaml_path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return data["dataset"]


def sync_gold_dataset(client: Any, yaml_path: Path = GOLD_YAML_PATH) -> int:
    """Crée le Dataset `gold-devis` s'il n'existe pas encore, puis upsert un
    item par document du YAML gold (id stable `gold-devis-{document_id}`).
    Idempotent : relancer ce script ne duplique jamais les items, met juste
    à jour ceux dont le YAML a changé. Retourne le nombre de documents
    synchronisés."""
    client.create_dataset(
        name=DATASET_NAME,
        description="Dataset gold devis — voir specs/ci-eval-gold-dataset.md",
    )

    documents = _load_gold_documents(yaml_path)
    for doc in documents:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=f"{DATASET_NAME}-{doc['document_id']}",
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

    count = sync_gold_dataset(Langfuse())
    print(f"Dataset '{DATASET_NAME}' synchronisé : {count} items.")


if __name__ == "__main__":
    main()
