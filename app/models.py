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


class ExtractionRun(BaseModel):
    id: int | None = None
    document_name: str
    results: list[ExtractionResult] = PydField(default_factory=list)
