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
        self.trace_calls = []
        self.llm_calls = []
        self.trace_handle = _SpyHandle()

    @contextmanager
    def trace_extraction(self, **kwargs):
        self.trace_calls.append(kwargs)
        yield self.trace_handle

    @contextmanager
    def trace_llm_call(self, **kwargs):
        handle = _SpyHandle()
        self.llm_calls.append({**kwargs, "handle": handle})
        yield handle


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

    assert len(tracer.trace_calls) == 1
    call = tracer.trace_calls[0]
    assert call["text"] == text
    assert call["provider"] == "google"
    assert call["model_id"] is None
    assert call["field_titles"] == ["Délai de paiement"]
    assert call["source_filename"] == "contrat.pdf"
    assert tracer.trace_handle.output == [r.model_dump() for r in results]


def test_extract_tags_openai_provider_from_model_id(monkeypatch):
    text = "Peu importe le contenu."
    annotated = data.AnnotatedDocument(extractions=[], text=text)
    monkeypatch.setattr(ner_langextract.langextract, "extract", lambda **kw: annotated)
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

    tracer = _SpyTracer()
    LangExtractNerExtractor(tracer=tracer).extract(text, [])

    assert tracer.trace_calls[0]["provider"] == "openai"
    assert tracer.trace_calls[0]["model_id"] == "gpt-4o-mini"
    assert tracer.trace_calls[0]["source_filename"] is None


def test_extract_traces_main_llm_call_as_generation_with_output(monkeypatch):
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
    monkeypatch.setenv("LLM_MODEL", "gemini-3.5-flash")

    tracer = _SpyTracer()
    LangExtractNerExtractor(tracer=tracer).extract(text, [field])

    assert len(tracer.llm_calls) == 1
    call = tracer.llm_calls[0]
    assert call["name"] == "extract-fields"
    assert call["model_id"] == "gemini-3.5-flash"
    assert "Délai de paiement" in call["prompt"]
    assert call["handle"].output == [{"field": "Délai de paiement", "value": "30 jours"}]


def test_extract_traces_arbitration_as_a_second_generation_when_conflict(monkeypatch):
    text = (
        "Par chèque ou virement à 30 jours après réception. "
        "15% à l'avancement sur situations mensuelles."
    )
    field = Field(
        id=1, key="cond", title="Condition de règlement", definition="d", examples=[]
    )
    first = data.Extraction(
        extraction_class="Condition de règlement",
        extraction_text="Par chèque ou virement à 30 jours.",
        char_interval=data.CharInterval(
            start_pos=text.index("Par chèque"),
            end_pos=text.index("Par chèque") + len("Par chèque ou virement à 30 jours."),
        ),
    )
    second = data.Extraction(
        extraction_class="Condition de règlement",
        extraction_text="15% à l'avancement sur situations mensuelles.",
        char_interval=data.CharInterval(
            start_pos=text.index("15%"),
            end_pos=text.index("15%") + len("15% à l'avancement sur situations mensuelles."),
        ),
    )
    main_annotated = data.AnnotatedDocument(extractions=[first, second], text=text)
    arbitration_annotated = data.AnnotatedDocument(
        extractions=[
            data.Extraction(
                extraction_class="selection",
                extraction_text="15% à l'avancement sur situations mensuelles.",
            )
        ],
        text="arbitration input",
    )
    calls = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return main_annotated if len(calls) == 1 else arbitration_annotated

    monkeypatch.setattr(ner_langextract.langextract, "extract", fake_extract)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    tracer = _SpyTracer()
    LangExtractNerExtractor(tracer=tracer).extract(text, [field])

    assert [c["name"] for c in tracer.llm_calls] == [
        "extract-fields",
        "arbitrate-conflict-Condition de règlement",
    ]
    assert "Condition de règlement" in tracer.llm_calls[1]["prompt"]
    assert "Par chèque ou virement à 30 jours." in tracer.llm_calls[1]["prompt"]
    assert "15% à l'avancement sur situations mensuelles." in tracer.llm_calls[1]["prompt"]
    assert tracer.llm_calls[1]["handle"].output == [
        "15% à l'avancement sur situations mensuelles."
    ]
