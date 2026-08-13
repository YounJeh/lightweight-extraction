import os

import pytest

from app.models import Field
from app.tools.ner_langextract import LangExtractNerExtractor
from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor
from tests.pdf_fixtures import SAMPLE_CONTRACT_FIELDS, build_sample_contract_pdf

pytestmark = pytest.mark.skipif(
    not os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"),
    reason="nécessite une vraie clé API Gemini (GOOGLE_GENERATIVE_AI_API_KEY)",
)


def _test_fields() -> list[Field]:
    return [
        Field(
            id=i,
            title=title,
            definition=f"Valeur du champ « {title} »",
            examples=[value],
        )
        for i, (title, value) in enumerate(SAMPLE_CONTRACT_FIELDS.items(), start=1)
    ]


@pytest.mark.live
def test_langextract_extracts_known_values_with_grounding():
    text = PyMuPDF4LlmTextExtractor().extract_text(build_sample_contract_pdf())
    fields = _test_fields()

    results = LangExtractNerExtractor().extract(text, fields)

    found = {r.field_title: r for r in results}
    for title, expected_value in SAMPLE_CONTRACT_FIELDS.items():
        assert title in found, f"champ {title!r} non extrait par LangExtract"
        result = found[title]
        assert result.value == expected_value
        assert result.source == "langextract"
        assert result.page_number is not None
        assert result.page_number >= 1
