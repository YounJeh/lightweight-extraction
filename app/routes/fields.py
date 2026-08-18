from fasthtml.common import RedirectResponse, UploadFile

from app.fields_import import import_fields
from app.models import FieldCreate, FieldExample, FieldUpdate
from app.repository import FieldRepository
from app.ui.components import error_banner, field_create_form, fields_table
from app.ui.layout import page


def _parse_examples(raw: str) -> list[FieldExample]:
    return [FieldExample(context=line.strip()) for line in raw.splitlines() if line.strip()]


def register_fields_routes(app, repo: FieldRepository):
    def _fields_page_with_error(message: str):
        return page(
            "Champs",
            error_banner(message),
            field_create_form(),
            fields_table(repo.list_all()),
        )

    # Route handlers are nested closures, so `.get`/`.post` are used
    # explicitly (see app/main.py for why bare `@rt(path)` name inference
    # doesn't apply here).
    @app.get("/fields")
    def get():
        return page("Champs", field_create_form(), fields_table(repo.list_all()))

    @app.post("/fields")
    def post(
        key: str,
        title: str,
        definition: str,
        examples: str = "",
        type: str = "text",
        section: str = "",
    ):
        try:
            repo.create(
                FieldCreate(
                    key=key,
                    title=title,
                    definition=definition,
                    section=section or None,
                    examples=_parse_examples(examples),
                    type=type,
                )
            )
        except ValueError as e:
            return _fields_page_with_error(str(e))
        return RedirectResponse("/fields", status_code=303)

    @app.post("/fields/{id}/update")
    def post_update(
        id: int,
        key: str,
        title: str,
        definition: str,
        examples: str = "",
        type: str = "text",
        section: str = "",
    ):
        try:
            repo.update(
                id,
                FieldUpdate(
                    key=key,
                    title=title,
                    definition=definition,
                    section=section or None,
                    examples=_parse_examples(examples),
                    type=type,
                ),
            )
        except ValueError as e:
            return _fields_page_with_error(str(e))
        return RedirectResponse("/fields", status_code=303)

    @app.post("/fields/{id}/delete")
    def post_delete(id: int):
        repo.delete(id)
        return RedirectResponse("/fields", status_code=303)

    @app.post("/fields/import")
    async def post_import(file: UploadFile):
        content = await file.read()
        result = import_fields(content, file.filename or "")
        if result.errors:
            return _fields_page_with_error("; ".join(result.errors))
        for field in result.fields:
            repo.upsert_by_key(field)
        return RedirectResponse("/fields", status_code=303)
