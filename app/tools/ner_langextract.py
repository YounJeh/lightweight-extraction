import os
import re

import langextract
from langextract import data

from app.models import ExtractionResult, Field, FieldType
from app.tools import type_coercion
from app.tools.pdf_pymupdf4llm import PAGE_SEPARATOR_RE
from app.tools.tracer import Tracer, build_tracer

_CONTEXT_CHARS = 40

_TYPE_INSTRUCTIONS = {
    "text": "",
    "int": " (nombre entier, ex. 30)",
    "float": " (nombre décimal, ex. 3.5)",
    "bool": "",
    "date": " (date au format ISO AAAA-MM-JJ)",
}

_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _typed_hint(example: str, field_type: FieldType) -> str | None:
    """Isole, dans un exemple en langage naturel, la sous-chaîne qui
    représente la valeur typée attendue — pour montrer au LLM, via le
    few-shot, que attributes['value'] doit être une valeur étroite/typée et
    non une recopie de extraction_text. None si rien n'est trouvé (le champ
    few-shot reste alors sans attributs, comme avant).

    Sans objet pour "bool" : un champ booléen (has_*) est une détection de
    présence, jamais recopié tel quel dans le texte source, donc il n'y a
    pas de sous-chaîne à isoler — voir _typed_value."""
    if field_type in ("int", "float"):
        match = _NUMBER_RE.search(example)
        return match.group(0).replace(",", ".") if match else None
    if field_type == "date":
        match = _ISO_DATE_RE.search(example)
        return match.group(0) if match else None
    return None


def _typed_attribute(extraction: "data.Extraction") -> str | None:
    """Valeur typée fournie par le LLM via attributes['value'], si présente
    et non vide — None sinon (l'appelant retombe alors sur extraction_text)."""
    value = (extraction.attributes or {}).get("value")
    return value if isinstance(value, str) and value else None


def _typed_value(field: Field, chosen: "data.Extraction") -> str:
    """Valeur typée à exposer pour ce champ. Pour "bool", ne dépend jamais du
    LLM : un champ booléen n'atteint ce point que s'il a un candidat groundé
    non vide (voir _group_grounded_candidates), donc sa seule présence ici
    vaut "oui" — demander au LLM de le reformuler via attributes['value']
    n'a pas de sens (il n'y a pas de "oui" littéral à recopier dans le
    contrat) et produisait un typed_value = extraction_text en repli,
    toujours rejeté par type_coercion.validate."""
    if field.type == "bool":
        return "oui" if chosen.extraction_text else "non"
    return _typed_attribute(chosen) or chosen.extraction_text


class LangExtractNerExtractor:
    """NerExtractor backed by LangExtract, calling the real Gemini model.

    Grounding (page_number/text_position) is derived from the char offsets
    LangExtract returns, mapped back to PyMuPDF4LlmTextExtractor's page
    separators — see specs/pdf-ner-real.md.
    """

    def __init__(self, tracer: Tracer | None = None):
        self._tracer = tracer or build_tracer()

    def extract(
        self,
        text: str,
        fields: list[Field],
        *,
        source_filename: str | None = None,
    ) -> list[ExtractionResult]:
        model_id = os.getenv("LLM_MODEL")
        with self._tracer.trace_extraction(
            text=text,
            provider=_provider_for(model_id),
            model_id=model_id,
            field_titles=[field.title for field in fields],
            source_filename=source_filename,
        ) as trace:
            results = self._extract(text, fields, model_id, self._tracer)
            trace.set_output([result.model_dump() for result in results])
            return results

    def _extract(
        self,
        text: str,
        fields: list[Field],
        model_id: str | None,
        tracer: Tracer,
    ) -> list[ExtractionResult]:
        example = _build_example(fields)
        api_key = _api_key_for(model_id)
        prompt_description = _prompt_description(fields)
        kwargs = {}
        if model_id:
            kwargs["model_id"] = model_id

        with tracer.trace_llm_call(
            name="extract-fields", model_id=model_id, prompt=prompt_description
        ) as generation:
            annotated = langextract.extract(
                text_or_documents=text,
                prompt_description=prompt_description,
                examples=[example] if example else None,
                api_key=api_key,
                show_progress=False,
                **kwargs,
            )
            generation.set_output(
                [
                    {"field": e.extraction_class, "value": e.extraction_text}
                    for e in (annotated.extractions or [])
                ]
            )

        candidates_by_field = _group_grounded_candidates(
            annotated.extractions or [], fields
        )
        fields_by_title = {field.title: field for field in fields}

        results = []
        for field_title, candidates in candidates_by_field.items():
            field = fields_by_title[field_title]
            chosen = _select_candidate(field, candidates, model_id, api_key, tracer)
            page_number, text_position = _locate(
                text, chosen.char_interval.start_pos, chosen.char_interval.end_pos
            )
            raw_value = _typed_value(field, chosen)
            type_error = type_coercion.validate(raw_value, field.type)
            results.append(
                ExtractionResult(
                    field_title=field_title,
                    value=chosen.extraction_text,
                    source="langextract",
                    page_number=page_number,
                    text_position=text_position,
                    value_type=field.type,
                    typed_value=raw_value,
                    type_error=type_error,
                )
            )
        return results


def _group_grounded_candidates(
    extractions: list["data.Extraction"], fields: list[Field]
) -> dict[str, list["data.Extraction"]]:
    """LangExtract chunks long text and queries every field on each chunk,
    so a field with no value in a given chunk still comes back as an
    Extraction — ungrounded (char_interval is None, per LangExtract's own
    semantics) and either empty or a hallucinated "no value" placeholder.
    Only grounded, non-blank extractions are real candidates."""
    field_titles = {field.title for field in fields}
    grouped: dict[str, list[data.Extraction]] = {}
    for extraction in extractions:
        if extraction.extraction_class not in field_titles:
            continue
        if extraction.char_interval is None or not extraction.extraction_text.strip():
            continue
        grouped.setdefault(extraction.extraction_class, []).append(extraction)
    return grouped


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _select_candidate(
    field: Field,
    candidates: list["data.Extraction"],
    model_id: str | None,
    api_key: str | None,
    tracer: Tracer,
) -> "data.Extraction":
    """0 candidat n'atteint jamais cette fonction (filtré en amont). 1 seul
    candidat -> accepté tel quel. Plusieurs candidats à la même valeur
    normalisée -> fusionnés sur la première occurrence, sans appel LLM. Sinon
    -> vrai conflit, arbitré par un second appel LLM."""
    ordered = sorted(candidates, key=lambda c: c.char_interval.start_pos)
    if len(ordered) == 1:
        return ordered[0]

    distinct_by_value: dict[str, data.Extraction] = {}
    for candidate in ordered:
        distinct_by_value.setdefault(_normalize(candidate.extraction_text), candidate)
    distinct = list(distinct_by_value.values())
    if len(distinct) == 1:
        return distinct[0]

    return _arbitrate(field, distinct, model_id, api_key, tracer)


def _arbitrate(
    field: Field,
    candidates: list["data.Extraction"],
    model_id: str | None,
    api_key: str | None,
    tracer: Tracer,
) -> "data.Extraction":
    """Plusieurs valeurs distinctes ont été extraites pour le même champ à
    des endroits différents du document (pas un artefact de chunking, un
    vrai conflit) — un second appel LLM, léger et hors grounding sur le
    document source, tranche parmi les candidats."""
    kwargs = {}
    if model_id:
        kwargs["model_id"] = model_id

    arbitration_prompt = _arbitration_prompt(field)
    arbitration_text = _arbitration_text(field, candidates)
    with tracer.trace_llm_call(
        name=f"arbitrate-conflict-{field.title}",
        model_id=model_id,
        prompt=f"{arbitration_prompt}\n\n{arbitration_text}",
    ) as generation:
        annotated = langextract.extract(
            text_or_documents=arbitration_text,
            prompt_description=arbitration_prompt,
            examples=[_arbitration_example()],
            api_key=api_key,
            show_progress=False,
            **kwargs,
        )
        generation.set_output(
            [e.extraction_text for e in (annotated.extractions or [])]
        )

    for extraction in annotated.extractions or []:
        if extraction.extraction_class != "selection":
            continue
        chosen_value = _normalize(extraction.extraction_text)
        for candidate in candidates:
            if _normalize(candidate.extraction_text) == chosen_value:
                return candidate

    # L'arbitrage n'a renvoyé aucune correspondance exacte (échec de
    # parsing) — repli déterministe plutôt que de perdre le champ.
    return candidates[0]


def _arbitration_text(field: Field, candidates: list["data.Extraction"]) -> str:
    lines = [f"Champ : {field.title}", f"Définition : {field.definition}", ""]
    lines += [
        f"Candidat {i} : {candidate.extraction_text}"
        for i, candidate in enumerate(candidates, start=1)
    ]
    return "\n".join(lines)


def _arbitration_prompt(field: Field) -> str:
    return (
        f"Plusieurs valeurs candidates ont été extraites pour le champ "
        f"« {field.title} » à des endroits différents du document. Choisis "
        "celle qui correspond le mieux à la définition du champ et "
        "recopie-la mot pour mot, à l'identique (extraction_class = "
        "'selection')."
    )


def _arbitration_example() -> "data.ExampleData":
    text = (
        "Champ : Montant total\n"
        "Définition : Montant total dû au titre du contrat.\n\n"
        "Candidat 1 : 12 000 EUR HT\n"
        "Candidat 2 : voir grille tarifaire en annexe"
    )
    return data.ExampleData(
        text=text,
        extractions=[
            data.Extraction(
                extraction_class="selection", extraction_text="12 000 EUR HT"
            )
        ],
    )


def _is_openai_model(model_id: str | None) -> bool:
    return bool(model_id) and model_id.startswith(("gpt-4", "gpt4.", "gpt-5", "gpt5."))


def _api_key_for(model_id: str | None) -> str | None:
    """LangExtract route vers OpenAI si model_id commence par gpt-4/gpt-5,
    sinon vers Gemini (défaut) — la clé doit correspondre au provider."""
    if _is_openai_model(model_id):
        return os.getenv("OPENAI_API_KEY")
    return os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")


def _provider_for(model_id: str | None) -> str:
    """Même routing que _api_key_for, exprimé comme tag de tracing."""
    return "openai" if _is_openai_model(model_id) else "google"


def _prompt_description(fields: list[Field]) -> str:
    lines = [
        "Pour chaque champ ci-dessous, si sa valeur est présente dans le "
        "texte, extrais-la littéralement (extraction_class = titre exact "
        "du champ). Si un format est indiqué entre parenthèses, fournis en "
        "plus la valeur dans ce format via l'attribut 'value' :"
    ]
    lines += [
        f"- {field.title} : {field.definition}{_TYPE_INSTRUCTIONS[field.type]}"
        for field in fields
    ]
    return "\n".join(lines)


def _example_attributes(field: Field) -> dict[str, str] | None:
    """attributes['value'] du few-shot pour ce champ — None pour les champs
    text/bool (pas de valeur typée à distinguer par le LLM, voir
    _typed_value) ou si aucun indice n'a pu être isolé dans l'exemple (voir
    _typed_hint)."""
    if field.type in ("text", "bool"):
        return None
    hint = _typed_hint(field.examples[0].context, field.type)
    return {"value": hint} if hint else None


def _build_example(fields: list[Field]) -> "data.ExampleData | None":
    """Un seul exemple few-shot synthétique, combinant le premier exemple de
    chaque champ qui en a un — pas d'exemple si aucun champ n'en fournit."""
    fields_with_examples = [f for f in fields if f.examples]
    if not fields_with_examples:
        return None
    lines = [
        f"{field.title} : {field.examples[0].context}" for field in fields_with_examples
    ]
    extractions = [
        data.Extraction(
            extraction_class=field.title,
            extraction_text=field.examples[0].context,
            attributes=_example_attributes(field),
        )
        for field in fields_with_examples
    ]
    return data.ExampleData(text="\n".join(lines), extractions=extractions)


def _locate(text: str, start_pos: int, end_pos: int) -> tuple[int, str]:
    page_number = len(PAGE_SEPARATOR_RE.findall(text[:start_pos])) + 1
    snippet = text[max(0, start_pos - _CONTEXT_CHARS) : end_pos + _CONTEXT_CHARS]
    snippet = PAGE_SEPARATOR_RE.sub(" ", snippet)
    snippet = " ".join(snippet.split())
    return page_number, snippet
