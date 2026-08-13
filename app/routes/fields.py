from fasthtml.common import RedirectResponse

from app.models import FieldCreate, FieldUpdate
from app.repository import FieldRepository
from app.ui.components import field_create_form, fields_table
from app.ui.layout import page


def _parse_examples(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def register_fields_routes(app, repo: FieldRepository):
    # Route handlers are nested closures, so `.get`/`.post` are used
    # explicitly (see app/main.py for why bare `@rt(path)` name inference
    # doesn't apply here).
    @app.get("/fields")
    def get():
        return page("Champs", fields_table(repo.list_all()), field_create_form())

    @app.post("/fields")
    def post(title: str, definition: str, examples: str = ""):
        repo.create(
            FieldCreate(
                title=title, definition=definition, examples=_parse_examples(examples)
            )
        )
        return RedirectResponse("/fields", status_code=303)

    @app.post("/fields/{id}/update")
    def post_update(id: int, title: str, definition: str, examples: str = ""):
        repo.update(
            id,
            FieldUpdate(
                title=title, definition=definition, examples=_parse_examples(examples)
            ),
        )
        return RedirectResponse("/fields", status_code=303)

    @app.post("/fields/{id}/delete")
    def post_delete(id: int):
        repo.delete(id)
        return RedirectResponse("/fields", status_code=303)
