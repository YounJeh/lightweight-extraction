"""Mesure le cold start du serveur NuExtract (Modal) et vérifie l'absence
de régression sur le corpus gold, sans passer par Langfuse -- boucle
rapide pour itérer sur les leviers de
tasks/plan-nuextract-cold-start-optimization.md (chaque redeploy de
scripts/modal_nuextract_server.py peut être remesuré en quelques appels,
sans créer un run Langfuse par tentative).

Chaque mesure est appendée à scripts/_cold_start_bench_cache/results.jsonl
(une ligne par cycle/run, jamais écrasée) -- historique brut de toutes les
tentatives, y compris les échecs. Voir docs/nuextract-cold-start-tests.md
pour la synthèse lisible.

Exécuté directement par l'agent (autorisation explicite, cadrage
`/idea-refine` de ce chantier -- voir
tasks/plan-nuextract-cold-start-optimization.md, Architecture Decisions) :
seule exception au principe général CLAUDE.md ("pas de run sur le corpus
gold par l'agent"), scopée à ce chantier.

Usage :
    uv run python scripts/nuextract_cold_start_bench.py cold-start --label baseline --cycles 3
    uv run python scripts/nuextract_cold_start_bench.py regress --label baseline
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from scripts import nuextract_client  # noqa: E402
from scripts.gold_dataset_eval import DATA_TEST_DIR, load_gold_fields  # noqa: E402
from scripts.gold_dataset_sync import GOLD_YAML_PATH, _load_gold_documents  # noqa: E402
from scripts.gold_matching import classify_field, precision_recall_f1  # noqa: E402

APP_NAME = "nuextract3"
RESULTS_PATH = Path(__file__).resolve().parent / "_cold_start_bench_cache" / "results.jsonl"

# Document gold fixe pour chaque cycle de mesure de cold start -- court (pas
# de windowing, un seul appel réseau) pour que le temps mesuré reflète le
# cold start serveur, pas le nombre d'appels côté client. document_id=1 du
# yaml gold (tests/data/dataset_gold_devis.yaml).
_BENCH_DOCUMENT_ID = 1

# Le conteneur peut mettre un instant à disparaître de `container list`
# après un `stop` -- attente bornée avant de considérer l'arrêt en échec.
# 60s s'est révélé trop court en réel avec le snapshot GPU activé (cycle 4
# du run gpu-snapshot-sleep-mode, voir docs/nuextract-cold-start-tests.md) :
# le teardown d'un conteneur dont l'état vient d'être snapshotté semble
# parfois plus lent qu'un teardown "normal".
_STOP_CONFIRM_TIMEOUT_SECONDS = 180.0


def _record(row: dict, *, results_path: Path = RESULTS_PATH) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("a") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False))


def _modal_json(*args: str) -> list[dict]:
    out = subprocess.run(
        ["modal", *args, "--json"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return json.loads(out) if out else []


def _app_id(app_name: str = APP_NAME) -> str:
    for app in _modal_json("app", "list"):
        if app.get("description") == app_name:
            return app["app_id"]
    raise RuntimeError(f"App Modal introuvable: {app_name}")


def force_cold_start(
    app_id: str, *, timeout: float = _STOP_CONFIRM_TIMEOUT_SECONDS
) -> None:
    """Stoppe tout conteneur actif de `app_id` et attend confirmation qu'il
    n'en reste aucun -- sans ça, une mesure pourrait tomber sur un
    conteneur encore chaud par accident."""
    for container in _modal_json("container", "list", "--app-id", app_id):
        container_id = container["container_id"]
        subprocess.run(["modal", "container", "stop", "-y", container_id], check=True)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _modal_json("container", "list", "--app-id", app_id):
            return
        time.sleep(2)
    raise TimeoutError(f"Conteneurs de {app_id} toujours actifs après {timeout}s")


def _bench_document() -> tuple[list, bytes]:
    fields_by_key = {f.key: f for f in load_gold_fields()}
    doc = next(
        d
        for d in _load_gold_documents(GOLD_YAML_PATH)
        if d["document_id"] == _BENCH_DOCUMENT_ID
    )
    fields = [fields_by_key[key] for key in doc["annotations"]]
    pdf_bytes = (DATA_TEST_DIR / doc["source_file"]).read_bytes()
    return fields, pdf_bytes


def measure_cold_start(
    *,
    label: str,
    cycles: int = 3,
    app_name: str = APP_NAME,
    results_path: Path = RESULTS_PATH,
) -> list[dict]:
    """Force un cold start puis mesure le temps jusqu'à la 1ère réponse
    réussie, répété `cycles` fois -- jamais un seul run (un snapshot Modal
    ne montre son effet qu'après quelques cold starts, voir le plan)."""
    app_id = _app_id(app_name)
    fields, pdf_bytes = _bench_document()
    rows = []
    for cycle in range(cycles):
        try:
            force_cold_start(app_id)
            forced = True
        except TimeoutError as exc:
            # Ne casse pas tout le run : le conteneur finira par tomber (ou
            # la requête suivante en verra un nouveau de toute façon) --
            # mieux vaut un cycle marqué "non garanti froid" que perdre les
            # cycles restants.
            print(f"WARNING: {exc}", file=sys.stderr)
            forced = False
        cold_start_seconds = 0.0

        def on_retry(delay: float) -> None:
            nonlocal cold_start_seconds
            cold_start_seconds += delay

        t0 = time.perf_counter()
        error = None
        try:
            nuextract_client.extract(pdf_bytes, fields, on_retry=on_retry)
        except Exception as exc:  # noqa: BLE001 -- on log l'échec, le bench continue
            error = repr(exc)
        elapsed = time.perf_counter() - t0

        row = {
            "kind": "cold_start",
            "label": label,
            "cycle": cycle,
            "elapsed_seconds": round(elapsed, 1),
            "cold_start_seconds": round(cold_start_seconds, 1),
            "forced_cold": forced,
            "error": error,
        }
        _record(row, results_path=results_path)
        rows.append(row)
    return rows


def check_gold_regression(*, label: str, results_path: Path = RESULTS_PATH) -> dict:
    """Rejoue l'extraction sur les 18 documents gold et compare aux valeurs
    annotées, via la même logique que `gold_dataset_eval.build_field_evaluator`
    (`gold_matching.classify_field`, importé tel quel) mais sans Langfuse --
    filet de non-régression rapide entre deux configs serveur, pas un score
    complet équivalent au run Langfuse officiel."""
    fields_by_key = {f.key: f for f in load_gold_fields()}
    title_to_key = {field.title: field.key for field in fields_by_key.values()}
    documents = _load_gold_documents(GOLD_YAML_PATH)

    tp = fp = fn = tn = 0
    per_document = []
    for doc in documents:
        fields = [fields_by_key[key] for key in doc["annotations"]]
        pdf_bytes = (DATA_TEST_DIR / doc["source_file"]).read_bytes()
        try:
            results = nuextract_client.extract(pdf_bytes, fields)
        except Exception as exc:  # noqa: BLE001 -- un document en échec ne doit
            # pas empêcher de scorer les autres (ex. bug windowing pré-existant,
            # hors scope de ce chantier cold-start -- voir choix_techniques.md).
            per_document.append(
                {"source_file": doc["source_file"], "error": repr(exc)}
            )
            continue
        output_by_key = {
            title_to_key[r.field_title]: r for r in results if r.field_title in title_to_key
        }

        doc_tp = doc_fp = doc_fn = 0
        for field_key, annotation in doc["annotations"].items():
            field = fields_by_key[field_key]
            extracted = output_by_key.get(field_key)
            outcomes = classify_field(
                field_key=field_key,
                field_type=field.type,
                gold_value=annotation.get("value"),
                gold_page=(annotation.get("evidence") or {}).get("page"),
                extracted_value=(extracted.typed_value or extracted.value) if extracted else None,
                extracted_page=None,
            )
            for outcome in outcomes:
                if outcome.kind == "tp":
                    tp += 1
                    doc_tp += 1
                elif outcome.kind == "fp":
                    fp += 1
                    doc_fp += 1
                elif outcome.kind == "fn":
                    fn += 1
                    doc_fn += 1
                else:
                    tn += 1
        per_document.append(
            {"source_file": doc["source_file"], "tp": doc_tp, "fp": doc_fp, "fn": doc_fn}
        )

    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    row = {
        "kind": "regression",
        "label": label,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "per_document": per_document,
    }
    _record(row, results_path=results_path)
    return row


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["cold-start", "regress"])
    parser.add_argument("--label", required=True, help="Nom du levier testé, ex. 'baseline'")
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()

    if args.mode == "cold-start":
        measure_cold_start(label=args.label, cycles=args.cycles)
    else:
        check_gold_regression(label=args.label)


if __name__ == "__main__":
    main()
