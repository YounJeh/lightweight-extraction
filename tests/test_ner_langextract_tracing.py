from contextlib import contextmanager

from langextract import data

from app.models import Field
from app.tools import ner_langextract
from app.tools.ner_langextract import LangExtractNerExtractor


class _SpyHandle:
    def __init__(self):
        self.output = None

    def set_output(self, output):
        self.output = output


class _SpyTracer:
    def __init__(self):
        self.calls = []
        self.handle = _SpyHandle()

    @contextmanager
    def trace_extraction(self, **kwargs):
        self.calls.append(kwargs)
        yield self.handle


def test_extract_passes_provider_model_fields_and_filename_to_tracer(monkeypatch):
    text = "Paiement à 30 jours après réception."
    field = Field(id=1, key="delai", title="Délai de paiement", definition="d", examples=[])
    candidate = data.Extraction(
        extraction_class="Délai de paiement",
        extraction_text="30 jours",
        char_interval=data.CharInterval(
            start_pos=text.index("30 jours"),
            end_pos=text.index("30 jours") + len("30 jours"),
        ),
    )
    annotated = data.AnnotatedDocument(extractions=[candidate], text=text)
    monkeypatch.setattr(ner_langextract.langextract, "extract", lambda **kw: annotated)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    tracer = _SpyTracer()
    results = LangExtractNerExtractor(tracer=tracer).extract(
        text, [field], source_filename="contrat.pdf"
    )

    assert len(tracer.calls) == 1
    call = tracer.calls[0]
    assert call["text"] == text
    assert call["provider"] == "google"
    assert call["model_id"] is None
    assert call["field_titles"] == ["Délai de paiement"]
    assert call["source_filename"] == "contrat.pdf"
    assert tracer.handle.output == [r.model_dump() for r in results]


def test_extract_tags_openai_provider_from_model_id(monkeypatch):
    text = "Peu importe le contenu."
    annotated = data.AnnotatedDocument(extractions=[], text=text)
    monkeypatch.setattr(ner_langextract.langextract, "extract", lambda **kw: annotated)
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

    tracer = _SpyTracer()
    LangExtractNerExtractor(tracer=tracer).extract(text, [])

    assert tracer.calls[0]["provider"] == "openai"
    assert tracer.calls[0]["model_id"] == "gpt-4o-mini"
    assert tracer.calls[0]["source_filename"] is None
