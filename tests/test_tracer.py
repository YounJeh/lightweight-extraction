import os

from app.tools.tracer import NoOpTracer, build_tracer


def test_default_test_environment_has_no_real_langfuse_keys():
    """Garde-fou : conftest.py doit toujours dépouiller LANGFUSE_PUBLIC_KEY/
    SECRET_KEY, même si le .env local du développeur en contient — sinon
    LangExtractNerExtractor() sans tracer explicite envoie de vraies traces
    vers Langfuse Cloud pendant la suite de tests (régression réelle : voir
    tests/conftest.py)."""
    assert "LANGFUSE_PUBLIC_KEY" not in os.environ
    assert "LANGFUSE_SECRET_KEY" not in os.environ
    assert isinstance(build_tracer(), NoOpTracer)


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


def test_noop_tracer_trace_llm_call_does_not_raise():
    with NoOpTracer().trace_llm_call(
        name="extract-fields", model_id="gemini-3.5-flash", prompt="..."
    ) as handle:
        handle.set_output([{"field": "x", "value": "y"}])


def test_noop_tracer_trace_pdf_extraction_does_not_raise():
    with NoOpTracer().trace_pdf_extraction(
        engine="pymupdf4llm",
        use_layout=True,
        ocr_language="fra",
        pages_ocr=[12],
        page_count=12,
        source_filename="devis.pdf",
    ) as handle:
        handle.set_metadata({"pages_ocr": [12]})
        handle.set_output("texte extrait...")


def test_noop_tracer_trace_run_does_not_raise():
    with NoOpTracer().trace_run(source_filename="devis.pdf") as handle:
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
