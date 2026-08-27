"""Rejoue le pipeline d'extraction réel sur le dataset gold
(tests/data/dataset_gold_devis.yaml) et trace le résultat dans Langfuse.

Voir specs/ci-eval-gold-dataset.md pour le contexte complet.
"""

import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import load_env  # noqa: E402
from app.db import get_connection, init_db  # noqa: E402
from app.fields_import import import_fields  # noqa: E402
from app.models import Field  # noqa: E402
from app.repository import FieldRepository  # noqa: E402
from app.tools.ner_langextract import LangExtractNerExtractor  # noqa: E402
from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor  # noqa: E402
from scripts.gold_dataset_sync import DATASET_NAME  # noqa: E402
from scripts.gold_matching import classify_field  # noqa: E402

GOLD_FIELDS_CSV = (
    Path(__file__).resolve().parent.parent / "tests" / "data" / "gold_devis_fields.csv"
)
DATA_TEST_DIR = Path(__file__).resolve().parent.parent / "data_test"


def load_gold_fields(csv_path: Path = GOLD_FIELDS_CSV) -> list[Field]:
    """Charge les définitions des champs du dataset gold depuis un CSV
    git-trackée (tests/data/gold_devis_fields.csv — DATASET GOLD.csv à la
    racine est obsolète pour ce chantier, voir specs/ci-eval-gold-dataset.md)
    et les seed dans une base SQLite jetable pour obtenir des `Field` réels
    (avec `id`), sans jamais toucher à data/app.db (gitignoré/éphémère,
    absent d'un runner CI frais)."""
    result = import_fields(csv_path.read_bytes(), csv_path.name)
    if result.errors:
        raise ValueError(f"gold_devis_fields.csv invalide : {result.errors}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "gold_eval.db"
        conn = get_connection(db_path)
        try:
            init_db(conn)
            repo = FieldRepository(conn)
            return [repo.upsert_by_key(field) for field in result.fields]
        finally:
            conn.close()


def build_task(
    fields_by_key: dict[str, Field],
    *,
    pdf_extractor: Any = None,
    ner_extractor: Any = None,
    data_test_dir: Path = DATA_TEST_DIR,
):
    """Task callable pour `dataset.run_experiment` — enveloppe fine du
    pipeline réel (`PyMuPDF4LlmTextExtractor` + `LangExtractNerExtractor`),
    aucune réimplémentation (voir Architecture Decisions du plan). Les deux
    extracteurs sont injectables pour les tests hors réseau ; en usage réel,
    laissés à leur valeur par défaut (`build_tracer()` résout le vrai
    `LangfuseTracer`, comme en production).

    `item.input` (posé par `gold_dataset_sync.sync_gold_dataset`) contient
    `source_file` et `field_keys` — la liste de clés à extraire pour ce
    document, résolue ici en objets `Field` réels (avec `id`/`title`,
    nécessaires à `LangExtractNerExtractor.extract`)."""
    pdf_extractor = pdf_extractor or PyMuPDF4LlmTextExtractor()
    ner_extractor = ner_extractor or LangExtractNerExtractor()

    def task(*, item, **kwargs) -> list[dict]:
        source_file = item.input["source_file"]
        field_keys = item.input["field_keys"]
        fields = [fields_by_key[key] for key in field_keys]

        pdf_bytes = (data_test_dir / source_file).read_bytes()
        text = pdf_extractor.extract_text(pdf_bytes)
        results = ner_extractor.extract(text, fields, source_filename=source_file)
        return [result.model_dump() for result in results]

    return task


def build_field_evaluator(fields_by_key: dict[str, Field]):
    """Évaluateur item-level : compare `output` (résultats d'extraction du
    pipeline réel, indexés par `field_title`) à `expected_output` (annotations
    gold, indexées par `field_key`) pour chaque champ demandé, et renvoie un
    score TP/FP/FN/TN par champ (`match:{field_key}`) + un exact-match
    document (`exact_match`) + le statut `human_validation` du document
    (voir metadata posée par `gold_dataset_sync.sync_gold_dataset`), pour que
    l'évaluateur run-level (Task 6) puisse exclure les documents non validés
    des métriques principales sans requête supplémentaire.

    `typed_value` préféré à `value` pour la comparaison — c'est la valeur
    déjà nettoyée par le pipeline (voir `app/tools/ner_langextract.py`),
    plus proche de ce que le gold encode que le texte groundé brut."""
    from langfuse.experiment import Evaluation

    title_to_key = {field.title: field.key for field in fields_by_key.values()}

    def field_evaluator(
        *, output=None, expected_output=None, metadata=None, **kwargs
    ) -> list[Evaluation]:
        output_by_key = {
            title_to_key[result["field_title"]]: result
            for result in (output or [])
            if result["field_title"] in title_to_key
        }

        evaluations: list[Evaluation] = []
        exact_match = True
        for field_key, annotation in (expected_output or {}).items():
            field = fields_by_key.get(field_key)
            if field is None:
                continue

            extracted = output_by_key.get(field_key) or {}
            outcomes = classify_field(
                field_key=field_key,
                field_type=field.type,
                gold_value=annotation.get("value"),
                gold_page=(annotation.get("evidence") or {}).get("page"),
                extracted_value=extracted.get("typed_value") or extracted.get("value"),
                extracted_page=extracted.get("page_number"),
            )
            for outcome in outcomes:
                if outcome.kind not in ("tp", "tn"):
                    exact_match = False
                evaluations.append(
                    Evaluation(
                        name=f"match:{field_key}",
                        value=outcome.kind,
                        metadata={"grounding_match": outcome.grounding_match},
                    )
                )

        evaluations.append(Evaluation(name="exact_match", value=exact_match))
        evaluations.append(
            Evaluation(
                name="human_validation",
                value=bool((metadata or {}).get("human_validation")),
            )
        )
        return evaluations

    return field_evaluator


def run_eval(client: Any = None, *, max_concurrency: int = 3):
    """Rejoue le pipeline réel sur les 14 items du Dataset Langfuse
    `gold-devis` (déjà synchronisé par `gold_dataset_sync.py`) via
    `dataset.run_experiment`. `max_concurrency` volontairement bas par
    défaut : OCR (RapidOCR) est coûteux en mémoire/CPU par document
    (~2 min sur un PDF de 12 pages, voir choix_techniques.md) et les appels
    Gemini sont soumis à des limites de débit — pas de bénéfice à paralléliser
    largement 14 documents."""
    if client is None:
        from langfuse import Langfuse

        client = Langfuse()

    fields_by_key = {field.key: field for field in load_gold_fields()}
    dataset = client.get_dataset(DATASET_NAME)
    task = build_task(fields_by_key)

    return dataset.run_experiment(
        name="gold-devis-eval",
        task=task,
        evaluators=[build_field_evaluator(fields_by_key)],
        max_concurrency=max_concurrency,
    )


def main() -> None:
    load_env()
    result = run_eval()
    print(result.format())


if __name__ == "__main__":
    main()
