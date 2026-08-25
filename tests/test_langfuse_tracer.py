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
        self.spans: list[_FakeSpan] = []
        self.observation_kwargs = None

    @contextmanager
    def start_as_current_observation(self, *, as_type, name, input):
        self.observation_kwargs = {"as_type": as_type, "name": name, "input": input}
        span = _FakeSpan()
        self.spans.append(span)
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

    assert fake_client.observation_kwargs == {
        "as_type": "span",
        "name": "ner_extraction",
        "input": "contenu du contrat",
    }
    assert captured["tags"] == ["google", "gemini-3.5-flash"]
    assert captured["metadata"] == {
        "field_titles": "Montant total, Date",
        "source_filename": "contrat.pdf",
    }
    assert fake_client.spans[0].output == [{"field_title": "Montant total", "value": "1000"}]
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
