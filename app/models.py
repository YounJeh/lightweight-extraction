from pydantic import BaseModel
from pydantic import Field as PydField


class FieldBase(BaseModel):
    title: str
    definition: str
    examples: list[str] = PydField(default_factory=list)


class FieldCreate(FieldBase):
    pass


class FieldUpdate(FieldBase):
    pass


class Field(FieldBase):
    id: int


class ExtractionResult(BaseModel):
    field_title: str
    value: str
    source: str = "mock"
    page_number: int | None = None
    text_position: str | None = None


class ExtractionGrounding(BaseModel):
    """Ligne de la table extraction_groundings — assemblée par le repository
    une fois l'id de l'ExtractionResult connu (post-INSERT), jamais produite
    directement par un NerExtractor."""

    result_id: int
    page_number: int
    text_position: str


class ExtractionRun(BaseModel):
    id: int | None = None
    document_name: str
    results: list[ExtractionResult] = PydField(default_factory=list)
