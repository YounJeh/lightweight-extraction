import os

import langextract
from langextract import data

from app.models import ExtractionResult, Field
from app.tools.pdf_pymupdf4llm import PAGE_SEPARATOR_RE

_CONTEXT_CHARS = 40


class LangExtractNerExtractor:
    """NerExtractor backed by LangExtract, calling the real Gemini model.

    Grounding (page_number/text_position) is derived from the char offsets
    LangExtract returns, mapped back to PyMuPDF4LlmTextExtractor's page
    separators — see specs/pdf-ner-real.md.
    """

    def extract(self, text: str, fields: list[Field]) -> list[ExtractionResult]:
        example = _build_example(fields)
        kwargs = {}
        model_id = os.getenv("LLM_MODEL")
        if model_id:
            kwargs["model_id"] = model_id

        annotated = langextract.extract(
            text_or_documents=text,
            prompt_description=_prompt_description(fields),
            examples=[example] if example else None,
            api_key=os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"),
            show_progress=False,
            **kwargs,
        )

        field_titles = {field.title for field in fields}
        results = []
        for extraction in annotated.extractions or []:
            if extraction.extraction_class not in field_titles:
                continue
            page_number, text_position = None, None
            if extraction.char_interval is not None:
                page_number, text_position = _locate(
                    text,
                    extraction.char_interval.start_pos,
                    extraction.char_interval.end_pos,
                )
            results.append(
                ExtractionResult(
                    field_title=extraction.extraction_class,
                    value=extraction.extraction_text,
                    source="langextract",
                    page_number=page_number,
                    text_position=text_position,
                )
            )
        return results


def _prompt_description(fields: list[Field]) -> str:
    lines = [
        "Pour chaque champ ci-dessous, si sa valeur est présente dans le "
        "texte, extrais-la littéralement (extraction_class = titre exact "
        "du champ) :"
    ]
    lines += [f"- {field.title} : {field.definition}" for field in fields]
    return "\n".join(lines)


def _build_example(fields: list[Field]) -> "data.ExampleData | None":
    """Un seul exemple few-shot synthétique, combinant le premier exemple de
    chaque champ qui en a un — pas d'exemple si aucun champ n'en fournit."""
    fields_with_examples = [f for f in fields if f.examples]
    if not fields_with_examples:
        return None
    lines = [f"{field.title} : {field.examples[0]}" for field in fields_with_examples]
    extractions = [
        data.Extraction(extraction_class=field.title, extraction_text=field.examples[0])
        for field in fields_with_examples
    ]
    return data.ExampleData(text="\n".join(lines), extractions=extractions)


def _locate(text: str, start_pos: int, end_pos: int) -> tuple[int, str]:
    page_number = len(PAGE_SEPARATOR_RE.findall(text[:start_pos])) + 1
    snippet = text[max(0, start_pos - _CONTEXT_CHARS) : end_pos + _CONTEXT_CHARS]
    snippet = PAGE_SEPARATOR_RE.sub(" ", snippet)
    snippet = " ".join(snippet.split())
    return page_number, snippet
