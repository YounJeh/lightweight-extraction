from contextlib import contextmanager

import pytest

import app.tools.langfuse_tracer as module


class _FakeSpan:
    def __init__(self):
        self.output = None

    def update(self, *, output):
        self.output = output


class _FakeClient:
    def __init__(self):
        self.flushed = False
        self.observations: list[dict] = []

    @contextmanager
    def start_as_current_observation(
        self, *, as_type, name, input, model=None, metadata=None
    ):
        span = _FakeSpan()
        self.observations.append(
            {
                "as_type": as_type,
                "name": name,
                "input": input,
                "model": model,
                "metadata": metadata,
                "span": span,
            }
        )
        yield span

    def flush(self):
        self.flushed = True


def _patch_client_and_propagate(monkeypatch):
    fake_client = _FakeClient()
    captured_propagate_kwargs = {}

    @contextmanager
    def fake_propagate_attributes(**kwargs):
        captured_propagate_kwargs.update(kwargs)
        yield

    monkeypatch.setattr(module, "get_client", lambda: fake_client)
    monkeypatch.setattr(module, "propagate_attributes", fake_propagate_attributes)
    return fake_client, captured_propagate_kwargs


def test_trace_extraction_sets_input_tags_metadata_output_and_flushes(monkeypatch):
    fake_client, captured = _patch_client_and_propagate(monkeypatch)

    tracer = module.LangfuseTracer()
    with tracer.trace_extraction(
        text="contenu du contrat",
        provider="google",
        model_id="gemini-3.5-flash",
        field_titles=["Montant total", "Date"],
        source_filename="contrat.pdf",
    ) as handle:
        handle.set_output([{"field_title": "Montant total", "value": "1000"}])

    assert len(fake_client.observations) == 1
    obs = fake_client.observations[0]
    assert obs["as_type"] == "span"
    assert obs["name"] == "ner_extraction"
    assert obs["input"] == "contenu du contrat"
    assert captured["tags"] == ["google", "gemini-3.5-flash"]
    assert captured["metadata"] == {
        "field_titles": "Montant total, Date",
        "source_filename": "contrat.pdf",
    }
    assert obs["span"].output == [{"field_title": "Montant total", "value": "1000"}]
    assert fake_client.flushed is True


def test_trace_extraction_without_model_id_only_tags_provider(monkeypatch):
    _fake_client, captured = _patch_client_and_propagate(monkeypatch)

    tracer = module.LangfuseTracer()
    with tracer.trace_extraction(
        text="x", provider="google", model_id=None, field_titles=[], source_filename=None
    ):
        pass

    assert captured["tags"] == ["google"]
    assert captured["metadata"] == {"field_titles": "", "source_filename": ""}


def test_trace_extraction_flushes_and_reraises_on_exception(monkeypatch):
    fake_client, _captured = _patch_client_and_propagate(monkeypatch)

    class BoomError(Exception):
        pass

    tracer = module.LangfuseTracer()
    with pytest.raises(BoomError):
        with tracer.trace_extraction(
            text="x", provider="google", model_id=None, field_titles=[], source_filename=None
        ):
            raise BoomError("extraction failed")

    assert fake_client.flushed is True


def test_trace_llm_call_opens_a_generation_typed_observation_with_model(monkeypatch):
    fake_client, _captured = _patch_client_and_propagate(monkeypatch)

    tracer = module.LangfuseTracer()
    with tracer.trace_llm_call(
        name="extract-fields", model_id="gemini-3.5-flash", prompt="extrait les champs..."
    ) as handle:
        handle.set_output([{"field": "Montant total", "value": "1000"}])

    assert len(fake_client.observations) == 1
    obs = fake_client.observations[0]
    assert obs["as_type"] == "generation"
    assert obs["name"] == "extract-fields"
    assert obs["input"] == "extrait les champs..."
    assert obs["model"] == "gemini-3.5-flash"
    assert obs["span"].output == [{"field": "Montant total", "value": "1000"}]
    # trace_llm_call ne flush pas lui-même — c'est trace_extraction qui flush
    # une fois l'ensemble (extraction + éventuel arbitrage) terminé.
    assert fake_client.flushed is False


def test_trace_llm_call_nested_inside_trace_extraction(monkeypatch):
    fake_client, _captured = _patch_client_and_propagate(monkeypatch)

    tracer = module.LangfuseTracer()
    with tracer.trace_extraction(
        text="x", provider="google", model_id=None, field_titles=[], source_filename=None
    ):
        with tracer.trace_llm_call(name="extract-fields", model_id=None, prompt="p"):
            pass

    assert [o["as_type"] for o in fake_client.observations] == ["span", "generation"]
    assert fake_client.flushed is True


def test_trace_pdf_extraction_opens_a_span_with_metadata_and_no_flush(monkeypatch):
    fake_client, _captured = _patch_client_and_propagate(monkeypatch)

    tracer = module.LangfuseTracer()
    with tracer.trace_pdf_extraction(
        engine="pymupdf4llm",
        use_layout=True,
        ocr_language="fra",
        pages_ocr=[12],
        page_count=12,
        source_filename="devis.pdf",
    ) as handle:
        handle.set_output("texte extrait...")

    assert len(fake_client.observations) == 1
    obs = fake_client.observations[0]
    assert obs["as_type"] == "span"
    assert obs["name"] == "pdf_extraction"
    assert obs["input"] == "devis.pdf"
    assert obs["metadata"] == {
        "engine": "pymupdf4llm",
        "use_layout": True,
        "ocr_language": "fra",
        "pages_ocr": [12],
        "page_count": 12,
    }
    assert obs["span"].output == "texte extrait..."
    # pas de flush ici — nested sous le span racine de l'appelant (Task 4)
    assert fake_client.flushed is False


def test_trace_pdf_extraction_nested_inside_trace_extraction(monkeypatch):
    fake_client, _captured = _patch_client_and_propagate(monkeypatch)

    tracer = module.LangfuseTracer()
    with tracer.trace_extraction(
        text="x", provider="google", model_id=None, field_titles=[], source_filename=None
    ):
        with tracer.trace_pdf_extraction(
            engine="pymupdf4llm",
            use_layout=True,
            ocr_language="fra",
            pages_ocr=[],
            page_count=1,
            source_filename=None,
        ):
            pass

    assert [o["as_type"] for o in fake_client.observations] == ["span", "span"]
    assert fake_client.flushed is True
