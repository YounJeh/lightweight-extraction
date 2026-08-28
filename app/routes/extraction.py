import asyncio
from pathlib import Path

from fasthtml.common import P, RedirectResponse, Request, UploadFile

from app.extraction_repository import ExtractionRunRepository
from app.gold_export import GoldExportError, export_to_gold
from app.repository import FieldRepository
from app.tools import NerExtractor, PdfTextExtractor
from app.tools.tracer import Tracer, build_tracer
from app.ui.components import (
    error_banner,
    extraction_form,
    extraction_result,
    extraction_runs_list,
    success_banner,
)
from app.ui.layout import page

DEFAULT_GOLD_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "data" / "dataset_gold_devis.yaml"
)


def register_extraction_routes(
    app,
    field_repo: FieldRepository,
    run_repo: ExtractionRunRepository,
    pdf_extractor: PdfTextExtractor,
    ner_extractor: NerExtractor,
    tracer: Tracer | None = None,
    gold_yaml_path: Path = DEFAULT_GOLD_YAML_PATH,
):
    tracer = tracer or build_tracer()

    def _extraction_page_with_error(message: str):
        return page(
            "Extraction",
            error_banner(message),
            extraction_form(field_repo.list_all()),
            extraction_runs_list(run_repo.list_runs()),
        )

    # Route handlers are nested closures, so `.get`/`.post` are used
    # explicitly (see app/main.py for why bare `@rt(path)` name inference
    # doesn't apply here).
    @app.get("/extraction")
    def get():
        fields = field_repo.list_all()
        runs = run_repo.list_runs()
        return page("Extraction", extraction_form(fields), extraction_runs_list(runs))

    @app.post("/extraction")
    async def post(pdf: UploadFile, field_ids: list[int] = []):
        if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
            return _extraction_page_with_error("seuls les fichiers PDF sont acceptés.")

        selected_fields = [f for f in field_repo.list_all() if f.id in field_ids]
        if not selected_fields:
            return _extraction_page_with_error("sélectionne au moins un champ à extraire.")

        pdf_bytes = await pdf.read()
        with tracer.trace_run(source_filename=pdf.filename):
            # extract_text can take minutes on a scanned PDF (OCR) — run it
            # off the event loop so it doesn't freeze the whole server for
            # every other request in the meantime. asyncio.to_thread
            # propagates the active contextvars (including the OTEL span
            # opened by trace_run above), so pdf_extraction still nests
            # correctly under it.
            text = await asyncio.to_thread(pdf_extractor.extract_text, pdf_bytes)
            results = ner_extractor.extract(
                text, selected_fields, source_filename=pdf.filename
            )

        run = run_repo.create_run(pdf.filename, results)
        return RedirectResponse(f"/extraction/runs/{run.id}", status_code=303)

    @app.post("/extraction/runs/delete")
    def post_delete_all():
        run_repo.delete_all_runs()
        return RedirectResponse("/extraction", status_code=303)

    @app.get("/extraction/runs/{id}")
    def get_run(id: int):
        run = run_repo.get_run(id)
        if run is None:
            return page("Extraction", P("Run introuvable."))
        title_to_key = {f.title: f.key for f in field_repo.list_all()}
        return page("Résultat d'extraction", extraction_result(run, title_to_key))

    @app.post("/extraction/runs/{id}/export-gold")
    async def post_export_gold(id: int, req: Request):
        run = run_repo.get_run(id)
        if run is None:
            return page("Extraction", P("Run introuvable."))

        title_to_key = {f.title: f.key for f in field_repo.list_all()}
        key_to_title = {key: title for title, key in title_to_key.items()}
        results_by_title = {r.field_title: r for r in run.results}

        form = await req.form()
        checked_keys = form.getlist("export_fields")

        annotations = {}
        for key in checked_keys:
            title = key_to_title.get(key)
            if title is None:
                # Clé cochée qui ne correspond plus à aucun champ connu
                # (ex. champ renommé/supprimé entre le rendu de la page et
                # la soumission) — jamais écrite dans le gold, plutôt qu'une
                # clé orpheline silencieuse dans un fichier versionné.
                continue
            result = results_by_title.get(title)
            fallback = (result.typed_value or result.value) if result else ""
            raw_value = form.get(f"value__{key}")
            value = (raw_value if raw_value is not None else fallback).strip() or None
            annotations[key] = {"value": value, "evidence": {"text": None, "page": None}}

        try:
            export_result = export_to_gold(
                gold_yaml_path, source_file=run.document_name, annotations=annotations
            )
        except GoldExportError as e:
            return page(
                "Résultat d'extraction", error_banner(str(e)), extraction_result(run, title_to_key)
            )

        status = "créée" if export_result.created else "mise à jour"
        message = (
            f"Entrée gold {status} (document_id={export_result.document_id}) : "
            f"{', '.join(export_result.field_keys)}."
        )
        return page(
            "Résultat d'extraction", success_banner(message), extraction_result(run, title_to_key)
        )
