import os
from contextlib import AbstractContextManager, nullcontext
from typing import Protocol


class Tracer(Protocol):
    def trace_extraction(
        self,
        *,
        provider: str,
        model_id: str | None,
        field_titles: list[str],
        source_filename: str | None,
    ) -> AbstractContextManager[None]: ...


class NoOpTracer:
    """Tracer par défaut : aucune clé Langfuse en environnement, ou en tests."""

    def trace_extraction(self, **_kwargs) -> AbstractContextManager[None]:
        return nullcontext()


def build_tracer() -> Tracer:
    """LangfuseTracer si des clés Langfuse sont en environnement, sinon
    NoOpTracer — import de LangfuseTracer différé pour ne pas rendre le SDK
    Langfuse nécessaire au chargement du module quand il n'est pas utilisé."""
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        from app.tools.langfuse_tracer import LangfuseTracer

        return LangfuseTracer()
    return NoOpTracer()
