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
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from app.models import Field  # noqa: E402
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
from scripts.gold_matching import _normalize_text  # noqa: E402
from scripts.nuextract_gold_langfuse_eval import (  # noqa: E402
    _cost_evaluation,
    _extraction_latency_evaluations,
    build_task,
)
from scripts.train_dataset_sync import DATASET_NAME  # noqa: E402

TRAIN_DATA_DIR = DATA_TEST_DIR / "train"


def build_evidence_similarity_evaluator(fields_by_key: dict[str, Field]):
    """Évaluateur item-level séparé de `build_field_evaluator` (importé,
    inchangé) : score de similarité continu -- pas d'exact match, page non
    pertinente (décision utilisateur, voir
    tasks/plan-nuextract-train-eval.md) -- entre `evidence.text` du gold et
    l'evidence prédite par NuExtract, par champ. Aucun score émis quand le
    gold n'a pas d'`evidence.text` pour ce champ (rien à comparer) ; `0.0`
    quand le gold en a une mais que l'extraction n'en produit aucune (un
    vrai manque, pas une absence de mesure)."""
    from langfuse.experiment import Evaluation

    title_to_key = {field.title: field.key for field in fields_by_key.values()}

    def evidence_similarity_evaluator(
        *, output=None, expected_output=None, metadata=None, **kwargs
    ) -> list[Evaluation]:
        extraction_results = (output or {}).get("extraction_results", [])
        output_by_key = {
            title_to_key[result["field_title"]]: result
            for result in extraction_results
            if result["field_title"] in title_to_key
        }

        evaluations: list[Evaluation] = []
        for field_key, annotation in (expected_output or {}).items():
            gold_text = (annotation.get("evidence") or {}).get("text")
            if not gold_text:
                continue

            extracted_text = (output_by_key.get(field_key) or {}).get("evidence")
            score = (
                0.0
                if not extracted_text
                else SequenceMatcher(
                    None, _normalize_text(gold_text), _normalize_text(extracted_text)
                ).ratio()
            )
            evaluations.append(Evaluation(name=f"evidence_similarity:{field_key}", value=score))

        return evaluations

    return evidence_similarity_evaluator


def _evidence_similarity_evaluations(item_results: list[Any]) -> list[Any]:
    """Moyenne des scores `evidence_similarity:{field_key}` (item-level,
    voir `build_evidence_similarity_evaluator`) par champ, + une moyenne
    macro (moyenne des moyennes par champ) -- pas de pooling TP/FP/FN comme
    `_field_metrics_evaluations` : ce n'est pas une classification, juste
    une moyenne de scores continus. Un champ sans aucun score (gold sans
    `evidence.text` pour tous les documents validés) est absent de
    l'agrégat, pas mis à `0.0`."""
    from langfuse.experiment import Evaluation

    scores_by_field: dict[str, list[float]] = defaultdict(list)
    for item_result in item_results:
        for ev in item_result.evaluations:
            if ev.name.startswith("evidence_similarity:"):
                field_key = ev.name.removeprefix("evidence_similarity:")
                scores_by_field[field_key].append(ev.value)

    evaluations = []
    field_means = []
    for field_key, scores in scores_by_field.items():
        mean = sum(scores) / len(scores)
        evaluations.append(Evaluation(name=f"evidence_similarity:{field_key}", value=mean))
        field_means.append(mean)

    if field_means:
        evaluations.append(
            Evaluation(
                name="evidence_similarity_macro", value=sum(field_means) / len(field_means)
            )
        )
    return evaluations


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
        evaluations.extend(_evidence_similarity_evaluations(validated))
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
        evaluators=[
            build_field_evaluator(fields_by_key),
            build_evidence_similarity_evaluator(fields_by_key),
        ],
        run_evaluators=[build_run_evaluator()],
        max_concurrency=max_concurrency,
    )


def main() -> None:
    load_env()
    result = run_eval()
    print(result.format())


if __name__ == "__main__":
    main()
