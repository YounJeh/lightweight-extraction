"""Export pur des champs validés d'un run d'extraction vers le gold
dataset YAML (tests/data/dataset_gold_devis.yaml en usage réel) — upsert
par `source_file`, fusion des annotations (pas de remplacement total).

Aucune dépendance FastHTML/sqlite3 ; le chemin YAML est toujours un
paramètre explicite, jamais de défaut interne, pour qu'un test ne puisse
jamais toucher le fichier réel par erreur (voir
tasks/plan-gold-export-from-extraction.md, Boundaries)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class GoldExportError(Exception):
    pass


@dataclass(frozen=True)
class GoldExportResult:
    document_id: int
    created: bool
    field_keys: list[str]


def export_to_gold(
    yaml_path: Path,
    *,
    source_file: str,
    annotations: dict[str, dict[str, Any]],
) -> GoldExportResult:
    """Ajoute ou met à jour l'entrée `source_file` du gold dataset avec
    `annotations` (`{field_key: {"value": ..., "evidence": {"text": None,
    "page": None}}}`). Nouveau `source_file` -> nouveau document,
    `document_id` = max existant + 1, `human_validation: True`. `source_file`
    déjà présent -> fusion dans l'`annotations` existante (les clés non
    renvoyées cette fois restent inchangées), même `document_id`."""
    if not annotations:
        raise GoldExportError("aucun champ coché")

    documents = _load_documents(yaml_path)

    existing = next((d for d in documents if d["source_file"] == source_file), None)
    if existing is not None:
        existing["annotations"].update(annotations)
        document_id = existing["document_id"]
        created = False
    else:
        document_id = max((d["document_id"] for d in documents), default=0) + 1
        documents.append(
            {
                "document_id": document_id,
                "source_file": source_file,
                "human_validation": True,
                "annotations": dict(annotations),
            }
        )
        created = True

    documents.sort(key=lambda d: d["document_id"])
    _write_documents(yaml_path, documents)

    return GoldExportResult(
        document_id=document_id, created=created, field_keys=sorted(annotations)
    )


def _load_documents(yaml_path: Path) -> list[dict[str, Any]]:
    if not yaml_path.exists():
        return []
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not data:
        return []
    return data.get("dataset") or []


def _write_documents(yaml_path: Path, documents: list[dict[str, Any]]) -> None:
    yaml_path.write_text(
        yaml.safe_dump(
            {"dataset": documents},
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
