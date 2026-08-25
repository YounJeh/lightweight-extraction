import os
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Protocol


class ObservationHandle(Protocol):
    def set_output(self, output: Any) -> None: ...


class Tracer(Protocol):
    def trace_extraction(
        self,
        *,
        text: str,
        provider: str,
        model_id: str | None,
        field_titles: list[str],
        source_filename: str | None,
    ) -> AbstractContextManager[ObservationHandle]: ...

    def trace_llm_call(
        self,
        *,
        name: str,
        model_id: str | None,
        prompt: str,
    ) -> AbstractContextManager[ObservationHandle]: ...


class _NoOpSpan:
    def set_output(self, output: Any) -> None:
        pass


class NoOpTracer:
    """Tracer par défaut : aucune clé Langfuse en environnement, ou en tests."""

    def trace_extraction(self, **_kwargs) -> AbstractContextManager[_NoOpSpan]:
        return nullcontext(_NoOpSpan())

    def trace_llm_call(self, **_kwargs) -> AbstractContextManager[_NoOpSpan]:
        return nullcontext(_NoOpSpan())


def build_tracer() -> Tracer:
    """LangfuseTracer si des clés Langfuse sont en environnement, sinon
    NoOpTracer — import de LangfuseTracer différé pour ne pas rendre le SDK
    Langfuse nécessaire au chargement du module quand il n'est pas utilisé."""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        from app.tools.langfuse_tracer import LangfuseTracer

        return LangfuseTracer()
    return NoOpTracer()
