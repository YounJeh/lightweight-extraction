"""Optimisation, champ par champ, des valeurs `Nom`/`Définition` de
`tests/data/gold_devis_fields.csv` via DSPy — jamais intégré à l'app en
production (LangExtract reste le moteur réel). Voir
`tasks/plan-dspy-prompt-tuning.md` pour le contexte et les décisions
d'architecture complètes.

Usage :
    uv run --no-sync python scripts/dspy_prompt_tuning.py
"""

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dspy  # noqa: E402

from app.config import load_env  # noqa: E402
from app.fields_import import _TYPE_MAP  # noqa: E402
from app.models import Field  # noqa: E402
from app.tools.ner_langextract import LangExtractNerExtractor, _api_key_for, _is_openai_model  # noqa: E402
from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor  # noqa: E402
from scripts import dspy_markdown_cache  # noqa: E402
from scripts.gold_dataset_eval import DATA_TEST_DIR, load_gold_fields  # noqa: E402
from scripts.gold_dataset_sync import GOLD_YAML_PATH, _load_gold_documents  # noqa: E402
from scripts.gold_matching import classify_field, precision_recall_f1  # noqa: E402
from scripts.text_slug import slugify_title  # noqa: E402

DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "tasks" / "dspy-prompt-tuning-results.csv"
_CSV_FIELDNAMES = ["section", "label", "Nom", "Définition", "Type", "exemple valeur", "Exemple texte", "source"]
_TYPE_MAP_INVERSE = {v: k for k, v in _TYPE_MAP.items()}


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
class FailureExample:
    """Un document où le candidat courant n'a pas matché le gold — donné en
    contexte au proposeur DSPy pour orienter la prochaine variante."""

    source_file: str
    gold_value: str
    extracted_value: str | None


@dataclass(frozen=True)
class FieldScore:
    f1: float
    precision: float | None
    recall: float | None
    tp: int
    fp: int
    fn: int
    failures: list[FailureExample]


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
    failures: list[FailureExample] = []
    for doc in gold_documents:
        annotation = doc["annotations"].get(field_key)
        if annotation is None:
            continue

        markdown = markdown_loader(doc["source_file"])
        results = ner_extractor.extract(markdown, fields, source_filename=doc["source_file"])
        extracted = next((r for r in results if r.field_title == candidate_title), None)
        extracted_value = (extracted.typed_value or extracted.value) if extracted else None

        outcomes = classify_field(
            field_key=field_key,
            field_type=target_field.type,
            gold_value=annotation.get("value"),
            gold_page=(annotation.get("evidence") or {}).get("page"),
            extracted_value=extracted_value,
            extracted_page=extracted.page_number if extracted else None,
        )
        doc_kinds = set()
        for outcome in outcomes:
            doc_kinds.add(outcome.kind)
            if outcome.kind == "tp":
                tp += 1
            elif outcome.kind == "fp":
                fp += 1
            elif outcome.kind == "fn":
                fn += 1

        if doc_kinds & {"fp", "fn"}:
            failures.append(
                FailureExample(
                    source_file=doc["source_file"],
                    gold_value=str(annotation.get("value")),
                    extracted_value=str(extracted_value) if extracted_value else None,
                )
            )

    precision, recall, f1 = precision_recall_f1(tp, fp, fn)
    return FieldScore(
        f1=f1 if f1 is not None else 0.0,
        precision=precision,
        recall=recall,
        tp=tp,
        fp=fp,
        fn=fn,
        failures=failures,
    )


@dataclass(frozen=True)
class FieldCandidate:
    title: str
    definition: str


class ProposeFieldPrompt(dspy.Signature):
    """Tu améliores un champ d'extraction NER pour un pipeline français
    d'extraction de devis/contrats. Propose un nouveau titre (`new_title`)
    et une nouvelle définition (`new_definition`), en français, plus clairs
    et sans ambiguïté pour un LLM d'extraction — même sens métier que
    l'original, mais reformulés pour réduire les erreurs listées dans
    `failure_summary` (si vide, propose simplement une formulation
    alternative à tester)."""

    field_type: str = dspy.InputField()
    current_title: str = dspy.InputField()
    current_definition: str = dspy.InputField()
    failure_summary: str = dspy.InputField(
        desc="Échecs observés avec la formulation actuelle, un par ligne, vide si aucun"
    )
    new_title: str = dspy.OutputField()
    new_definition: str = dspy.OutputField()


def _format_failure_summary(failures: list[FailureExample]) -> str:
    if not failures:
        return ""
    return "\n".join(
        f"- {f.source_file} : attendu {f.gold_value!r}, extrait {f.extracted_value!r}"
        for f in failures
    )


def propose_candidates(
    field: Field,
    *,
    failures: list[FailureExample],
    n: int,
    lm: dspy.LM,
) -> list[FieldCandidate]:
    """Propose `n` variantes de `title`/`definition` pour `field`, en tenant
    compte de `failures` (documents où la formulation courante a échoué).
    Un appel LM par variante (température de `lm` régit la diversité entre
    les appels — pas d'API de complétions multiples DSPy dédiée utilisée
    ici, un `dspy.Predict` par candidat suffit et reste simple à tester)."""
    predict = dspy.Predict(ProposeFieldPrompt)
    failure_summary = _format_failure_summary(failures)

    candidates = []
    for _ in range(n):
        result = predict(
            field_type=field.type,
            current_title=field.title,
            current_definition=field.definition,
            failure_summary=failure_summary,
            lm=lm,
        )
        candidates.append(FieldCandidate(title=result.new_title, definition=result.new_definition))
    return candidates


@dataclass(frozen=True)
class FieldResult:
    field_key: str
    baseline_title: str
    baseline_definition: str
    baseline_f1: float
    best_title: str
    best_definition: str
    best_label: str
    best_f1: float


def optimize_field(
    field_key: str,
    *,
    all_fields: list[Field],
    gold_documents: list[dict[str, Any]],
    n_candidates: int,
    n_rounds: int,
    ner_extractor: Any,
    markdown_loader: Callable[[str], str],
    lm: dspy.LM,
    score_fn: Callable[..., FieldScore] = score_field_candidate,
    propose_fn: Callable[..., list[FieldCandidate]] = propose_candidates,
) -> FieldResult:
    """Baseline (valeurs CSV actuelles) -> `n_rounds` rounds de
    `n_candidates` propositions chacun, en repartant à chaque round du
    meilleur candidat connu (et de ses échecs, pour orienter la
    proposition suivante). Ne renvoie jamais un résultat pire que la
    baseline : un candidat ne remplace le meilleur connu que s'il le bat
    strictement en F1."""
    target_field = next(f for f in all_fields if f.key == field_key)

    def score(title: str, definition: str) -> FieldScore:
        return score_fn(
            field_key,
            title,
            definition,
            all_fields=all_fields,
            gold_documents=gold_documents,
            ner_extractor=ner_extractor,
            markdown_loader=markdown_loader,
        )

    baseline_score = score(target_field.title, target_field.definition)
    best_title, best_definition, best_score = (
        target_field.title,
        target_field.definition,
        baseline_score,
    )

    for _ in range(n_rounds):
        current_field = target_field.model_copy(
            update={"title": best_title, "definition": best_definition}
        )
        candidates = propose_fn(current_field, failures=best_score.failures, n=n_candidates, lm=lm)
        for candidate in candidates:
            candidate_score = score(candidate.title, candidate.definition)
            if candidate_score.f1 > best_score.f1:
                best_title, best_definition, best_score = (
                    candidate.title,
                    candidate.definition,
                    candidate_score,
                )

    return FieldResult(
        field_key=field_key,
        baseline_title=target_field.title,
        baseline_definition=target_field.definition,
        baseline_f1=baseline_score.f1,
        best_title=best_title,
        best_definition=best_definition,
        best_label=slugify_title(best_title),
        best_f1=best_score.f1,
    )


def _field_csv_row(field: Field, *, label: str, title: str, definition: str) -> dict[str, str]:
    example = field.examples[0] if field.examples else None
    return {
        "section": field.section or "",
        "label": label,
        "Nom": title,
        "Définition": definition,
        "Type": _TYPE_MAP_INVERSE[field.type],
        "exemple valeur": (example.value if example else None) or "",
        "Exemple texte": example.context if example else "",
        "source": (example.source if example else None) or "",
    }


def write_results_csv(
    all_fields: list[Field], results_by_key: dict[str, FieldResult], output_path: Path
) -> None:
    """CSV complet au format `tests/data/gold_devis_fields.csv` : les champs
    optimisés (présents dans `results_by_key`) portent leur meilleur
    `title`/`definition`/`label` trouvé, les autres sont recopiés
    inchangés — le fichier reste copiable-collable tel quel par-dessus le
    CSV existant, même en n'ayant optimisé qu'un sous-ensemble de champs
    via `--field`."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        for field in all_fields:
            result = results_by_key.get(field.key)
            if result is None:
                writer.writerow(
                    _field_csv_row(field, label=field.key, title=field.title, definition=field.definition)
                )
            else:
                writer.writerow(
                    _field_csv_row(
                        field,
                        label=result.best_label,
                        title=result.best_title,
                        definition=result.best_definition,
                    )
                )


def run(
    field_keys: list[str],
    *,
    all_fields: list[Field],
    gold_documents: list[dict[str, Any]],
    n_candidates: int,
    n_rounds: int,
    output_path: Path,
    optimize_fn: Callable[..., FieldResult] = optimize_field,
    **optimize_kwargs: Any,
) -> dict[str, FieldResult]:
    """Optimise chaque champ de `field_keys`, affiche `baseline_f1 ->
    best_f1` sur stdout, puis écrit le CSV complet (Tâche 8). `optimize_fn`
    injectable pour les tests (aucun appel LLM réel dans la suite `pytest`
    par défaut) ; en usage réel, laissé à `optimize_field`."""
    results_by_key: dict[str, FieldResult] = {}
    for field_key in field_keys:
        result = optimize_fn(
            field_key,
            all_fields=all_fields,
            gold_documents=gold_documents,
            n_candidates=n_candidates,
            n_rounds=n_rounds,
            **optimize_kwargs,
        )
        results_by_key[field_key] = result
        print(f"{field_key} : {result.baseline_f1:.3f} -> {result.best_f1:.3f}")

    write_results_csv(all_fields, results_by_key, output_path)
    print(f"Résultats écrits dans {output_path}")
    return results_by_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        help="Clé de champ à optimiser (répétable) — défaut : tous les champs de gold_devis_fields.csv",
    )
    parser.add_argument("--n-candidates", type=int, default=5)
    parser.add_argument("--n-rounds", type=int, default=2)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    load_env()
    all_fields = load_gold_fields()
    gold_documents = _load_gold_documents(GOLD_YAML_PATH)
    field_keys = args.fields or [field.key for field in all_fields]

    run(
        field_keys,
        all_fields=all_fields,
        gold_documents=gold_documents,
        n_candidates=args.n_candidates,
        n_rounds=args.n_rounds,
        output_path=args.output,
        ner_extractor=LangExtractNerExtractor(),
        markdown_loader=build_markdown_loader(
            data_test_dir=DATA_TEST_DIR, pdf_extractor=PyMuPDF4LlmTextExtractor()
        ),
        lm=build_dspy_lm(os.getenv("LLM_MODEL")),
    )


if __name__ == "__main__":
    main()
