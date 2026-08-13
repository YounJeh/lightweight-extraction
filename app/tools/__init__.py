from typing import Protocol

from app.models import ExtractionResult, Field


class PdfTextExtractor(Protocol):
    def extract_text(self, pdf_bytes: bytes) -> str: ...


class NerExtractor(Protocol):
    def extract(self, text: str, fields: list[Field]) -> list[ExtractionResult]: ...
