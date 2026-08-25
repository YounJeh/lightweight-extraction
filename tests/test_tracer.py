from app.tools.tracer import NoOpTracer, build_tracer


def test_noop_tracer_context_manager_does_not_raise():
    with NoOpTracer().trace_extraction(
        provider="google",
        model_id="gemini-3.5-flash",
        field_titles=["Montant total"],
        source_filename="contrat.pdf",
    ):
        pass


def test_noop_tracer_accepts_missing_optional_fields():
    with NoOpTracer().trace_extraction(
        provider="google", model_id=None, field_titles=[], source_filename=None
    ):
        pass


def test_build_tracer_returns_noop_when_langfuse_keys_absent(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert isinstance(build_tracer(), NoOpTracer)


def test_build_tracer_returns_noop_when_only_public_key_present(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    assert isinstance(build_tracer(), NoOpTracer)
