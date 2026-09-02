from types import SimpleNamespace

from app.models import ExtractionResult, Field
from scripts.nuextract_gold_langfuse_eval import build_task

_NUMERO_DEVIS = Field(
    id=1, key="numero_devis", title="Numéro de devis", definition="d", type="text"
)


class _FakeExtractor:
    def __init__(self, results: list[ExtractionResult]):
        self.results = results
        self.received: dict | None = None

    def __call__(self, pdf_bytes: bytes, fields: list[Field]) -> list[ExtractionResult]:
        self.received = {"pdf_bytes": pdf_bytes, "fields": fields}
        return self.results


def test_build_task_reads_the_referenced_pdf_and_extracts_selected_fields(tmp_path):
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake-bytes")
    extractor = _FakeExtractor(
        [
            ExtractionResult(
                field_title="Numéro de devis", value="n°6952", source="nuextract", typed_value="n°6952"
            )
        ]
    )

    task = build_task(
        {"numero_devis": _NUMERO_DEVIS}, extractor=extractor, data_test_dir=tmp_path
    )
    item = SimpleNamespace(input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]})

    output = task(item=item)

    assert extractor.received == {"pdf_bytes": b"%PDF-fake-bytes", "fields": [_NUMERO_DEVIS]}
    assert output["extraction_results"] == [
        {
            "field_title": "Numéro de devis",
            "value": "n°6952",
            "source": "nuextract",
            "page_number": None,
            "text_position": None,
            "value_type": None,
            "typed_value": "n°6952",
            "type_error": None,
        }
    ]
    assert output["latency_seconds"] >= 0


def test_build_task_resolves_only_the_fields_listed_for_this_item(tmp_path):
    other = Field(id=2, key="nom_societe", title="Nom de la société", definition="d", type="text")
    (tmp_path / "devis.pdf").write_bytes(b"%PDF")
    extractor = _FakeExtractor([])

    task = build_task(
        {"numero_devis": _NUMERO_DEVIS, "nom_societe": other},
        extractor=extractor,
        data_test_dir=tmp_path,
    )
    item = SimpleNamespace(input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]})

    task(item=item)

    assert extractor.received["fields"] == [_NUMERO_DEVIS]
