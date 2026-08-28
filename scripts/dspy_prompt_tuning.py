"""Optimisation, champ par champ, des valeurs `Nom`/`Définition` de
`tests/data/gold_devis_fields.csv` via DSPy — jamais intégré à l'app en
production (LangExtract reste le moteur réel). Voir
`tasks/plan-dspy-prompt-tuning.md` pour le contexte et les décisions
d'architecture complètes.

Usage :
    uv run --no-sync python scripts/dspy_prompt_tuning.py
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dspy  # noqa: E402

from app.models import Field  # noqa: E402
from app.tools.ner_langextract import _api_key_for, _is_openai_model  # noqa: E402
from scripts import dspy_markdown_cache  # noqa: E402
from scripts.gold_matching import classify_field, precision_recall_f1  # noqa: E402


def build_dspy_lm(model_id: str | None) -> dspy.LM:
    """`dspy.LM` routé vers le même provider/clé que `LangExtractNerExtractor`
    (voir `app/tools/ner_langextract.py:_is_openai_model`/`_api_key_for`) —
    pas de deuxième logique de routing à maintenir. `model` suit la
    convention LiteLLM `"provider/model"` attendue par `dspy.LM`.

    Contrairement à LangExtract (qui tolère `model_id=None` et retombe sur
    son propre défaut interne), DSPy a besoin d'une chaîne de modèle
    explicite : `LLM_MODEL` doit être renseigné dans l'environnement pour
    utiliser DSPy, cohérent avec le choix déjà fait ailleurs dans ce projet
    de ne jamais coder un modèle Gemini par défaut en dur
    (voir `specs/pdf-ner-real.md`)."""
    if not model_id:
        raise ValueError(
            "LLM_MODEL doit être défini dans l'environnement pour utiliser DSPy "
            "(pas de modèle par défaut codé en dur, voir specs/pdf-ner-real.md)."
        )
    provider = "openai" if _is_openai_model(model_id) else "gemini"
    return dspy.LM(f"{provider}/{model_id}", api_key=_api_key_for(model_id))


def build_markdown_loader(
    *,
    data_test_dir: Path,
    pdf_extractor: Any,
    cache_dir: Path = dspy_markdown_cache.CACHE_DIR,
) -> Callable[[str], str]:
    """Ferme sur `data_test_dir`/`pdf_extractor`/`cache_dir` pour offrir à
    `score_field_candidate` un chargeur `source_file -> markdown` qui ne
    connaît ni le disque ni l'extracteur PDF — juste le nom du fichier."""

    def load(source_file: str) -> str:
        pdf_bytes = (data_test_dir / source_file).read_bytes()
        return dspy_markdown_cache.get_markdown(
            source_file, pdf_bytes, pdf_extractor=pdf_extractor, cache_dir=cache_dir
        )

    return load


@dataclass(frozen=True)
class FieldScore:
    f1: float
    precision: float | None
    recall: float | None
    tp: int
    fp: int
    fn: int


def score_field_candidate(
    field_key: str,
    candidate_title: str,
    candidate_definition: str,
    *,
    all_fields: list[Field],
    gold_documents: list[dict[str, Any]],
    ner_extractor: Any,
    markdown_loader: Callable[[str], str],
) -> FieldScore:
    """F1 (et TP/FP/FN poolés sur tous les documents) d'un candidat
    `title`/`definition` pour `field_key`, contre `gold_documents`. Les
    champs de `all_fields` autres que `field_key` sont passés tels quels à
    `ner_extractor` — optimisation field-par-field, jamais jointe (voir
    Architecture Decisions du plan)."""
    target_field = next(f for f in all_fields if f.key == field_key)
    fields = [
        f.model_copy(update={"title": candidate_title, "definition": candidate_definition})
        if f.key == field_key
        else f
        for f in all_fields
    ]

    tp = fp = fn = 0
    for doc in gold_documents:
        annotation = doc["annotations"].get(field_key)
        if annotation is None:
            continue

        markdown = markdown_loader(doc["source_file"])
        results = ner_extractor.extract(markdown, fields, source_filename=doc["source_file"])
        extracted = next((r for r in results if r.field_title == candidate_title), None)

        outcomes = classify_field(
            field_key=field_key,
            field_type=target_field.type,
            gold_value=annotation.get("value"),
            gold_page=(annotation.get("evidence") or {}).get("page"),
            extracted_value=(extracted.typed_value or extracted.value) if extracted else None,
            extracted_page=extracted.page_number if extracted else None,
        )
        for outcome in outcomes:
            if outcome.kind == "tp":
                tp += 1
            elif outcome.kind == "fp":
                fp += 1
            elif outcome.kind == "fn":
                fn += 1

    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    return FieldScore(
        f1=f1 if f1 is not None else 0.0,
        precision=precision,
        recall=recall,
        tp=tp,
        fp=fp,
        fn=fn,
    )
