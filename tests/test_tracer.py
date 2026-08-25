from app.tools.tracer import NoOpTracer, build_tracer


def test_noop_tracer_context_manager_does_not_raise():
    with NoOpTracer().trace_extraction(
        text="contenu",
        provider="google",
        model_id="gemini-3.5-flash",
        field_titles=["Montant total"],
        source_filename="contrat.pdf",
    ) as handle:
        handle.set_output([{"field_title": "Montant total", "value": "1000"}])


def test_noop_tracer_accepts_missing_optional_fields():
    with NoOpTracer().trace_extraction(
        text="", provider="google", model_id=None, field_titles=[], source_filename=None
    ) as handle:
        handle.set_output(None)


def test_build_tracer_returns_noop_when_langfuse_keys_absent(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert isinstance(build_tracer(), NoOpTracer)


def test_build_tracer_returns_noop_when_only_public_key_present(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert isinstance(build_tracer(), NoOpTracer)


def test_build_tracer_returns_langfuse_tracer_when_keys_present(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    from app.tools.langfuse_tracer import LangfuseTracer

    tracer = build_tracer()

    assert isinstance(tracer, LangfuseTracer)
