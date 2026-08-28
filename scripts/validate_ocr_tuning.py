"""Validation locale (pas de LLM, pas de Langfuse) de deux optimisations
candidates pour l'extraction PDF -> texte : baisser `ocr_dpi` (A) et
court-circuiter l'OCR sous un seuil de surface d'image (B). Voir
docs/ideas/validation-optimisation-ocr.md pour le contexte complet.

Mesure, pour chaque config testée, le temps d'extraction et la présence
(sous-chaîne normalisée) de chaque valeur gold non nulle dans le texte
markdown brut produit — pas d'appel NER/LLM, proxy volontairement simple et
gratuit pour isoler l'effet de l'extraction PDF (voir "Not Doing" du plan).

Usage :
    uv run --no-sync python scripts/validate_ocr_tuning.py
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402
import pymupdf4llm  # noqa: E402
from pymupdf4llm.helpers import utils as pymupdf4llm_utils  # noqa: E402
from pymupdf4llm.helpers.document_layout import select_ocr_function  # noqa: E402

import app.tools.pdf_pymupdf4llm  # noqa: E402,F401 side effect: pymupdf4llm.use_layout(True)
from scripts.gold_dataset_eval import DATA_TEST_DIR  # noqa: E402
from scripts.gold_dataset_sync import GOLD_YAML_PATH, _load_gold_documents  # noqa: E402
from scripts.gold_matching import _normalize_text  # noqa: E402


def load_gold_values(yaml_path: Path = GOLD_YAML_PATH) -> list[tuple[str, str, str]]:
    """(source_file, field_key, value) pour chaque annotation non nulle du
    yaml gold — mêmes documents que `gold_dataset_eval.py`, sans passer par
    Langfuse."""
    documents = _load_gold_documents(yaml_path)
    rows = []
    for doc in documents:
        for field_key, annotation in doc["annotations"].items():
            value = annotation.get("value")
            if value is not None and str(value).strip():
                rows.append((doc["source_file"], field_key, str(value)))
    return rows


def extract_with_config(
    pdf_bytes: bytes, *, ocr_dpi: int, area_skip_threshold: float | None = None
) -> str:
    """Reproduit `PyMuPDF4LlmTextExtractor.extract_text` avec `ocr_dpi` et
    un seuil de saut d'OCR paramétrables — pour tester plusieurs configs
    sans toucher à `app/`. `area_skip_threshold=None` reproduit le
    comportement actuel de l'app à l'identique (aucun saut)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        base_ocr_function = select_ocr_function()
        if not callable(base_ocr_function):
            return pymupdf4llm.to_markdown(
                doc, page_separators=True, ocr_language="fra", ocr_dpi=ocr_dpi
            )

        def ocr_function(page, **kwargs):
            if area_skip_threshold is not None:
                area = pymupdf4llm_utils.analyze_page(page).get("img_area", 0)
                if area < area_skip_threshold:
                    return
            return base_ocr_function(page, **kwargs)

        return pymupdf4llm.to_markdown(
            doc,
            page_separators=True,
            ocr_language="fra",
            ocr_dpi=ocr_dpi,
            ocr_function=ocr_function,
        )
    finally:
        doc.close()


def value_present(text: str, value: str) -> bool:
    return _normalize_text(value) in _normalize_text(text)


# Palier A (dpi) isolé -- seuil B désactivé, dpi=150 = comportement actuel
# de l'app (référence).
A_CONFIGS = [
    {"name": "dpi150_baseline", "ocr_dpi": 150, "area_skip_threshold": None},
    {"name": "dpi120", "ocr_dpi": 120, "area_skip_threshold": None},
    {"name": "dpi100", "ocr_dpi": 100, "area_skip_threshold": None},
    {"name": "dpi90", "ocr_dpi": 90, "area_skip_threshold": None},
    {"name": "dpi72", "ocr_dpi": 72, "area_skip_threshold": None},
]

# Seuil B isolé -- dpi=150 (référence). Bracketent la zone observée dans
# docs/ideas/validation-optimisation-ocr.md : la page 12 de référence
# (104__DEVIS, à préserver) a img_area=0.0164 ; les logos Tournan/Super-U
# (à éliminer si possible) sont à 0.026-0.039.
# 0.02 : juste au-dessus de la page 12, ne devrait toucher aucun logo.
# 0.05 : au-dessus de tous les logos connus, devrait tous les éliminer.
# 0.10 : plus agressif, pour voir si ça casse quelque chose au-delà des logos.
B_CONFIGS = [
    {"name": "threshold_0.02", "ocr_dpi": 150, "area_skip_threshold": 0.02},
    {"name": "threshold_0.05", "ocr_dpi": 150, "area_skip_threshold": 0.05},
    {"name": "threshold_0.10", "ocr_dpi": 150, "area_skip_threshold": 0.10},
]


def combined_configs(threshold: float) -> list[dict]:
    """Paliers dpi (mêmes valeurs que A_CONFIGS) combinés à un seuil B
    fixé -- à appeler une fois le seuil B choisi sur la base du rapport de
    la matrice B seule (report(), config B sans nouvelle régression et le
    meilleur temps)."""
    return [
        {
            "name": f"combined_dpi{dpi}_t{threshold}",
            "ocr_dpi": dpi,
            "area_skip_threshold": threshold,
        }
        for dpi in (150, 120, 100, 90, 72)
    ]

CACHE_DIR = Path(__file__).resolve().parent / "_ocr_tuning_cache"
RESULTS_PATH = CACHE_DIR / "results.jsonl"


def _load_done_keys(results_path: Path) -> set[tuple[str, str]]:
    if not results_path.exists():
        return set()
    done = set()
    for line in results_path.read_text().splitlines():
        row = json.loads(line)
        done.add((row["source_file"], row["config"]))
    return done


def run_matrix(
    configs: list[dict],
    source_files: list[str],
    *,
    cache_dir: Path = CACHE_DIR,
    results_path: Path = RESULTS_PATH,
) -> None:
    """Extrait chaque (source_file, config) une seule fois, met le texte en
    cache sur disque (`cache_dir/<source_file>__<config>.md`) et append une
    ligne JSON par résultat dans `results_path` (temps + texte présent/non)
    -- relançable sans recalcul : les couples déjà présents dans
    `results_path` sont sautés."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    done = _load_done_keys(results_path)
    gold_rows = load_gold_values()

    with results_path.open("a") as out:
        for source_file in source_files:
            gold_for_file = [
                (key, value) for f, key, value in gold_rows if f == source_file
            ]
            pdf_bytes = (DATA_TEST_DIR / source_file).read_bytes()

            for config in configs:
                if (source_file, config["name"]) in done:
                    continue

                t0 = time.time()
                text = extract_with_config(
                    pdf_bytes,
                    ocr_dpi=config["ocr_dpi"],
                    area_skip_threshold=config["area_skip_threshold"],
                )
                elapsed = time.time() - t0

                text_path = cache_dir / f"{source_file}__{config['name']}.md"
                text_path.write_text(text)

                missing = [key for key, value in gold_for_file if not value_present(text, value)]
                row = {
                    "source_file": source_file,
                    "config": config["name"],
                    "elapsed_seconds": round(elapsed, 1),
                    "gold_values_total": len(gold_for_file),
                    "gold_values_missing": missing,
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(
                    f"{source_file:55s} {config['name']:18s} "
                    f"{elapsed:6.1f}s  manquantes: {missing or '-'}"
                )


def _load_results(results_path: Path = RESULTS_PATH) -> list[dict]:
    if not results_path.exists():
        return []
    return [json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]


def rescore_cache(cache_dir: Path = CACHE_DIR, results_path: Path = RESULTS_PATH) -> None:
    """Recalcule `gold_values_missing` pour chaque résultat déjà en cache,
    contre le yaml gold *actuel* -- sans ré-extraire (le texte mis en cache
    ne dépend pas des valeurs gold, seul le scoring en dépend). À relancer
    après toute correction de `tests/data/dataset_gold_devis.yaml`, sinon
    `report()` reste basé sur un scoring périmé."""
    rows = _load_results(results_path)
    gold_by_file: dict[str, list[tuple[str, str]]] = {}
    for source_file, key, value in load_gold_values():
        gold_by_file.setdefault(source_file, []).append((key, value))

    updated = []
    for row in rows:
        text_path = cache_dir / f"{row['source_file']}__{row['config']}.md"
        if not text_path.exists():
            updated.append(row)
            continue
        text = text_path.read_text()
        gold_for_file = gold_by_file.get(row["source_file"], [])
        missing = [key for key, value in gold_for_file if not value_present(text, value)]
        updated.append(
            {
                **row,
                "gold_values_total": len(gold_for_file),
                "gold_values_missing": missing,
            }
        )

    with results_path.open("w") as out:
        for row in updated:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(updated)} résultats re-scorés contre le yaml gold actuel.")


def report(
    results_path: Path = RESULTS_PATH, baseline_config: str = "dpi150_baseline"
) -> None:
    """Résumé par config : temps total, valeurs gold manquantes, et surtout
    les *nouvelles* régressions -- valeurs présentes à `baseline_config`
    (comportement actuel de l'app) mais absentes dans cette config, pour ne
    pas confondre une régression introduite par le changement testé avec
    une valeur que le pipeline ratait déjà avant (voir Open Questions,
    docs/ideas/validation-optimisation-ocr.md)."""
    rows = _load_results(results_path)
    if not rows:
        print(f"Aucun résultat dans {results_path} -- lancer matrix-a/matrix-b d'abord.")
        return

    by_config: dict[str, list[dict]] = {}
    for row in rows:
        by_config.setdefault(row["config"], []).append(row)

    baseline_missing = {
        row["source_file"]: set(row["gold_values_missing"])
        for row in by_config.get(baseline_config, [])
    }
    if not baseline_missing:
        print(f"Pas de résultats pour la config de référence '{baseline_config}' -- ")
        print("les nouvelles régressions ne peuvent pas être distinguées des pertes préexistantes.")

    header = f"{'config':18s} {'docs':>4s} {'temps total':>12s} {'manquantes':>12s} {'régressions':>12s}"
    print(header)
    print("-" * len(header))
    for config_name, config_rows in sorted(by_config.items()):
        total_time = sum(r["elapsed_seconds"] for r in config_rows)
        total_values = sum(r["gold_values_total"] for r in config_rows)
        total_missing = sum(len(r["gold_values_missing"]) for r in config_rows)

        regressions: list[tuple[str, list[str]]] = []
        for r in config_rows:
            already_missing = baseline_missing.get(r["source_file"], set())
            new = [k for k in r["gold_values_missing"] if k not in already_missing]
            if new:
                regressions.append((r["source_file"], new))

        print(
            f"{config_name:18s} {len(config_rows):4d} {total_time:10.1f}s  "
            f"{total_missing:3d}/{total_values:<7d} {len(regressions):5d} documents"
        )
        for source_file, keys in regressions:
            print(f"    RÉGRESSION  {source_file}  ->  {keys}")


def _cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["list", "matrix-a", "matrix-b", "report", "rescore"],
        default="list",
        nargs="?",
    )
    args = parser.parse_args()

    if args.command == "rescore":
        rescore_cache()
        return

    if args.command == "report":
        report()
        return

    if args.command == "list":
        rows = load_gold_values()
        by_file: dict[str, int] = {}
        for source_file, _field_key, _value in rows:
            by_file[source_file] = by_file.get(source_file, 0) + 1
        print(f"{len(rows)} valeurs gold non nulles, {len(by_file)} documents")
        for source_file, count in sorted(by_file.items()):
            exists = (DATA_TEST_DIR / source_file).exists()
            flag = "" if exists else "  <-- FICHIER INTROUVABLE"
            print(f"  {count:2d}  {source_file}{flag}")
        return

    source_files = sorted({f for f, _k, _v in load_gold_values()})
    configs = A_CONFIGS if args.command == "matrix-a" else B_CONFIGS
    run_matrix(configs, source_files)


if __name__ == "__main__":
    _cli()
