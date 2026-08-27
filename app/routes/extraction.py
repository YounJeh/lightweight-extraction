from fasthtml.common import P, RedirectResponse, UploadFile

from app.extraction_repository import ExtractionRunRepository
from app.repository import FieldRepository
from app.tools import NerExtractor, PdfTextExtractor
from app.tools.tracer import Tracer, build_tracer
from app.ui.components import (
    error_banner,
    extraction_form,
    extraction_result,
    extraction_runs_list,
)
from app.ui.layout import page


def register_extraction_routes(
    app,
    field_repo: FieldRepository,
    run_repo: ExtractionRunRepository,
    pdf_extractor: PdfTextExtractor,
    ner_extractor: NerExtractor,
    tracer: Tracer | None = None,
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
            text = pdf_extractor.extract_text(pdf_bytes)
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
        return page("Résultat d'extraction", extraction_result(run))
