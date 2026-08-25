from contextlib import contextmanager
from typing import Any

from langfuse import get_client, propagate_attributes


class _SpanHandle:
    def __init__(self, span: Any):
        self._span = span

    def set_output(self, output: Any) -> None:
        self._span.update(output=output)


class LangfuseTracer:
    """Tracer réel : une trace "ner_extraction" par appel, avec le texte
    source en input, les résultats d'extraction en output (via set_output),
    et provider/model_id/champs/fichier source en tags/metadata. Clés/host
    lus depuis les variables d'environnement standard du SDK
    (LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL) — voir docstring du package
    `langfuse`.

    Flush synchrone à la fin de chaque trace : ce process tourne en continu
    (serveur FastHTML sans hook de shutdown fiable à ce stade), donc flush
    par requête reste la façon la plus simple de garantir qu'aucune trace
    n'est perdue au lieu de compter sur le flush périodique en arrière-plan
    du SDK."""

    def __init__(self):
        self._client = get_client()

    @contextmanager
    def trace_extraction(
        self,
        *,
        text: str,
        provider: str,
        model_id: str | None,
        field_titles: list[str],
        source_filename: str | None,
    ):
        tags = [provider] + ([model_id] if model_id else [])
        metadata = {
            "field_titles": ", ".join(field_titles),
            "source_filename": source_filename or "",
        }
        try:
            with self._client.start_as_current_observation(
                as_type="span", name="ner_extraction", input=text
            ) as span:
                with propagate_attributes(
                    trace_name="ner_extraction", tags=tags, metadata=metadata
                ):
                    yield _SpanHandle(span)
        finally:
            self._client.flush()

    @contextmanager
    def trace_llm_call(self, *, name: str, model_id: str | None, prompt: str):
        """Un appel LangExtract réel (extraction principale ou arbitrage) —
        typé "generation" (pas "span") pour que le nom de modèle et,
        potentiellement, les coûts/tokens soient exploitables côté Langfuse.
        Nested sous le span ouvert par trace_extraction (contexte OTEL actif),
        pas de flush ici : trace_extraction flush une fois l'ensemble
        terminé."""
        with self._client.start_as_current_observation(
            as_type="generation", name=name, input=prompt, model=model_id
        ) as generation:
            yield _SpanHandle(generation)
