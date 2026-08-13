from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor
from tests.pdf_fixtures import SAMPLE_CONTRACT_FIELDS, build_sample_contract_pdf


def test_sample_contract_pdf_is_parsable_and_contains_expected_values():
    pdf_bytes = build_sample_contract_pdf()

    text = PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)

    for expected_value in SAMPLE_CONTRACT_FIELDS.values():
        assert expected_value in text


def test_sample_contract_pdf_extracted_text_is_deterministic():
    text_a = PyMuPDF4LlmTextExtractor().extract_text(build_sample_contract_pdf())
    text_b = PyMuPDF4LlmTextExtractor().extract_text(build_sample_contract_pdf())

    assert text_a == text_b
