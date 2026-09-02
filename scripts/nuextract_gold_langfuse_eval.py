"""Rejoue le pipeline NuExtract (scripts/nuextract_client.py) sur le
Dataset Langfuse "gold-devis" existant, en réutilisant le scoring déjà
pipeline-agnostique de scripts/gold_dataset_eval.py (import direct, aucune
modification de ce fichier) — comparable dans la vue "Dataset Runs" de
Langfuse aux runs LangExtract existants (gold-devis-eval).

Voir docs/ideas/nuextract-langfuse-eval.md et
tasks/plan-nuextract-langfuse-eval.md pour le contexte complet.

`name` (passé à `dataset.run_experiment`) n'a pas besoin d'embarquer une
date : Langfuse auto-génère un `run_name` unique par appel (`name` +
timestamp ISO, voir `DatasetClient.run_experiment` dans le SDK installé —
même mécanisme que l'exemple officiel "Comparing different model
versions") — plusieurs runs avec le même `name` restent des runs Langfuse
distincts et comparables.

Le run réel contre le vrai serveur NuExtract reste à la charge de l'humain
(règle CLAUDE.md — ce chantier n'est pas du DSPy, pas d'exception ici).

Usage :
    uv run python scripts/nuextract_gold_langfuse_eval.py
"""

import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from app.models import ExtractionResult, Field  # noqa: E402
from scripts import nuextract_client  # noqa: E402
from scripts.gold_dataset_eval import (  # noqa: E402
    DATA_TEST_DIR,
    _exact_match_accuracy,
    _field_metrics_evaluations,
    _grounding_accuracy,
    _item_evaluation_value,
    _latency_evaluations,
    _percentile,
    build_field_evaluator,
    load_gold_fields,
)
from scripts.gold_dataset_sync import DATASET_NAME  # noqa: E402

# `on_retry` accepté en kwarg optionnel par les extracteurs réels
# (`nuextract_client.extract`) -- Callable[..., ...] plutôt qu'une
# signature positionnelle stricte, pour ne pas obliger chaque extracteur
# factice de test à le déclarer explicitement.
Extractor = Callable[..., list[ExtractionResult]]

# Tarif GPU L4 Modal (€/h), voir docs/ideas/nuextract-langfuse-eval.md —
# constante en dur (décision utilisateur), à ajuster manuellement si le
# type de GPU/la région change.
_GPU_COST_PER_HOUR = 0.80


def build_task(
    fields_by_key: dict[str, Field],
    *,
    extractor: Extractor | None = None,
    data_test_dir: Path = DATA_TEST_DIR,
):
    """Task callable pour `dataset.run_experiment` — même contrat que
    `gold_dataset_eval.build_task`, sans étape PDF→texte séparée (NuExtract
    lit les pages directement, voir `nuextract_client.extract`) ni
    `ocr_page_count` (ce pipeline n'OCRise rien)."""
    extractor = extractor or nuextract_client.extract

    def task(*, item, **kwargs) -> dict:
        source_file = item.input["source_file"]
        field_keys = item.input["field_keys"]
        fields = [fields_by_key[key] for key in field_keys]

        # Accumulateur local à cet appel de task() -- thread-safe sous
        # max_concurrency>1 (chaque exécution a sa propre closure, aucun
        # état partagé entre documents concurrents). Voir
        # docs/ideas/nuextract-cold-start-latency.md.
        cold_start_seconds = 0.0

        def on_retry(delay: float) -> None:
            nonlocal cold_start_seconds
            cold_start_seconds += delay

        start = time.perf_counter()
        pdf_bytes = (data_test_dir / source_file).read_bytes()
        results = extractor(pdf_bytes, fields, on_retry=on_retry)
        latency_seconds = time.perf_counter() - start

        return {
            "extraction_results": [result.model_dump() for result in results],
            "latency_seconds": latency_seconds,
            "cold_start_seconds": cold_start_seconds,
        }

    return task


def _cost_evaluation(item_results: list[Any]) -> Any:
    """Coût approximatif du run : somme des `latency_seconds` par item /
    3600 x `_GPU_COST_PER_HOUR` — traite chaque item comme s'il avait tourné
    séquentiellement, donc **surestime** sous concurrence (les items
    concurrents se chevauchent en horloge murale). Décidé en cadrage :
    préférable à un `0.0` silencieux (voir le `cost_usd_total` figé de
    `gold_dataset_eval.build_run_evaluator`, LangExtract n'exposant aucun
    usage token)."""
    from langfuse.experiment import Evaluation

    total_seconds = sum(
        r.output.get("latency_seconds", 0.0)
        for r in item_results
        if isinstance(r.output, dict)
    )
    cost = total_seconds / 3600 * _GPU_COST_PER_HOUR
    return Evaluation(
        name="cost_usd_total",
        value=cost,
        comment=(
            f"Approximation : somme des latences item ({total_seconds:.1f}s) / 3600 x "
            f"{_GPU_COST_PER_HOUR}€/h (GPU L4 Modal) -- majorant sous concurrence "
            "(les items concurrents se chevauchent en horloge murale, cette somme "
            "les traite comme séquentiels)."
        ),
    )


def _extraction_latency_evaluations(item_results: list[Any]) -> list[Any]:
    """p50/p95 de la latence "nettoyée" (`latency_seconds -
    cold_start_seconds`) par item -- le temps d'attente de retry (cold-start,
    essentiellement) exclu, contrairement à `latency_p50/p95` (réutilisé de
    `gold_dataset_eval.py`, mesure brute qui inclut ce temps d'attente).
    Même calcul de percentile que l'existant (`_percentile`, importé, pas
    réimplémenté). Voir docs/ideas/nuextract-cold-start-latency.md."""
    from langfuse.experiment import Evaluation

    net_latencies = sorted(
        r.output["latency_seconds"] - r.output.get("cold_start_seconds", 0.0)
        for r in item_results
        if isinstance(r.output, dict) and "latency_seconds" in r.output
    )
    if not net_latencies:
        return []
    return [
        Evaluation(name="extraction_latency_p50_seconds", value=_percentile(net_latencies, 50)),
        Evaluation(name="extraction_latency_p95_seconds", value=_percentile(net_latencies, 95)),
    ]


def build_run_evaluator():
    """Évaluateur run-level, composé à partir des helpers déjà réutilisables
    de `gold_dataset_eval.py` (importés, jamais modifiés) + un coût réel
    calculé (`_cost_evaluation`) à la place du `0.0` figé de
    `gold_dataset_eval.build_run_evaluator`. Pas de split OCR
    (`_ocr_split_evaluations`) : ce pipeline n'OCRise rien, la métrique
    n'aurait aucun sens."""
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
    """`name` passé à `dataset.run_experiment` — stable par modèle (`/`
    remplacé, invalide dans certains contextes d'URL). Pas de date : voir
    docstring du module, Langfuse auto-génère un `run_name` unique par
    appel."""
    return f"gold-devis-nuextract-{model.replace('/', '_')}"


def run_eval(
    client: Any = None,
    *,
    max_concurrency: int = 14,
    model: str = nuextract_client._DEFAULT_MODEL,
):
    """Rejoue le pipeline NuExtract sur les items du Dataset Langfuse
    `gold-devis` (déjà synchronisé par `gold_dataset_sync.py`) via
    `dataset.run_experiment`. `max_concurrency=14` (= nombre de documents
    gold) : vLLM bat les requêtes concurrentes en interne (continuous
    batching), un seul conteneur Modal (`max_containers=1`) les absorbe
    sans coût GPU supplémentaire — décidé en cadrage."""
    if client is None:
        from langfuse import Langfuse

        client = Langfuse()

    fields_by_key = {field.key: field for field in load_gold_fields()}
    dataset = client.get_dataset(DATASET_NAME)
    task = build_task(fields_by_key)

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
