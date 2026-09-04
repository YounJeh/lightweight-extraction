"""Rejoue le pipeline NuExtract (scripts/nuextract_client.py) sur le
Dataset Langfuse "train-devis" (synchronisé par
scripts/train_dataset_sync.py), en réutilisant par import (jamais copiés
ni modifiés) le scoring de scripts/gold_dataset_eval.py et les helpers
NuExtract-spécifiques de scripts/nuextract_gold_langfuse_eval.py --
`build_task` en particulier n'est pas réécrit, seul `data_test_dir` change
(les PDF train vivent dans data_test/train/, pas data_test/).

Voir tasks/plan-nuextract-train-eval.md pour le contexte complet.

Le run réel contre le vrai serveur NuExtract reste normalement à la charge
de l'humain (règle CLAUDE.md), mais l'utilisateur a explicitement autorisé
Claude à l'exécuter pour ce dataset train (contrairement au gold, jamais
concerné par cette exception).

Usage :
    uv run python scripts/nuextract_train_langfuse_eval.py
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from scripts import nuextract_client  # noqa: E402
from scripts.gold_dataset_eval import (  # noqa: E402
    DATA_TEST_DIR,
    _exact_match_accuracy,
    _field_metrics_evaluations,
    _grounding_accuracy,
    _item_evaluation_value,
    _latency_evaluations,
    build_field_evaluator,
    load_gold_fields,
)
from scripts.nuextract_gold_langfuse_eval import (  # noqa: E402
    _cost_evaluation,
    _extraction_latency_evaluations,
    build_task,
)
from scripts.train_dataset_sync import DATASET_NAME  # noqa: E402

TRAIN_DATA_DIR = DATA_TEST_DIR / "train"


def build_run_evaluator():
    """Évaluateur run-level : mêmes métriques que
    `nuextract_gold_langfuse_eval.build_run_evaluator` (importé nulle
    part -- il n'expose pas de point d'extension pour ajouter
    `evidence_similarity`, Task 5 -- donc réécrit ici en composant les
    mêmes helpers importés)."""
    from langfuse.experiment import Evaluation

    def run_evaluator(*, item_results, **kwargs) -> list[Any]:
        validated = [
            r for r in item_results if _item_evaluation_value(r, "human_validation") is True
        ]

        evaluations = [
            Evaluation(name="documents_evaluated", value=len(validated)),
            Evaluation(
                name="documents_excluded_unvalidated",
                value=len(item_results) - len(validated),
            ),
        ]
        evaluations.extend(_field_metrics_evaluations(validated))
        evaluations.append(_exact_match_accuracy(validated))
        evaluations.append(_grounding_accuracy(validated))
        evaluations.extend(_latency_evaluations(validated))
        evaluations.extend(_extraction_latency_evaluations(validated))
        evaluations.append(_cost_evaluation(validated))
        return evaluations

    return run_evaluator


def _run_name(model: str) -> str:
    return f"train-devis-nuextract-{model.replace('/', '_')}"


def run_eval(
    client: Any = None,
    *,
    max_concurrency: int = 14,
    model: str = nuextract_client._DEFAULT_MODEL,
):
    """Rejoue le pipeline NuExtract sur les items du Dataset Langfuse
    `train-devis`. `max_concurrency=14` : même valeur par défaut que le
    gold (vLLM absorbe les requêtes concurrentes via continuous batching
    sur un seul conteneur Modal, voir nuextract_gold_langfuse_eval.py) --
    pas de raison de la faire dépendre du nombre de documents (34 ici
    contre 14 pour le gold)."""
    if client is None:
        from langfuse import Langfuse

        client = Langfuse()

    fields_by_key = {field.key: field for field in load_gold_fields()}
    dataset = client.get_dataset(DATASET_NAME)
    task = build_task(fields_by_key, data_test_dir=TRAIN_DATA_DIR)

    return dataset.run_experiment(
        name=_run_name(model),
        task=task,
        evaluators=[build_field_evaluator(fields_by_key)],
        run_evaluators=[build_run_evaluator()],
        max_concurrency=max_concurrency,
    )


def main() -> None:
    load_env()
    result = run_eval()
    print(result.format())


if __name__ == "__main__":
    main()
