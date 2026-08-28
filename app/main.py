import sqlite3
from pathlib import Path

from fasthtml.common import Link, Meta, RedirectResponse, fast_app, serve

from app.auth import basic_auth_beforeware
from app.config import load_env
from app.db import DEFAULT_DB_PATH, get_connection, init_db
from app.extraction_repository import ExtractionRunRepository
from app.repository import FieldRepository
from app.routes.extraction import DEFAULT_GOLD_YAML_PATH, register_extraction_routes
from app.routes.fields import register_fields_routes
from app.tools import NerExtractor, PdfTextExtractor
from app.tools.ner_langextract import LangExtractNerExtractor
from app.tools.pdf_pymupdf4llm import PyMuPDF4LlmTextExtractor

load_env()


def create_app(
    conn: sqlite3.Connection,
    pdf_extractor: PdfTextExtractor | None = None,
    ner_extractor: NerExtractor | None = None,
    gold_yaml_path: Path = DEFAULT_GOLD_YAML_PATH,
):
    init_db(conn)
    app, _ = fast_app(
        pico=False,
        before=basic_auth_beforeware(),
        hdrs=(
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Link(rel="stylesheet", href="/static/style.css"),
        ),
    )

    # Route handlers below are nested closures (not top-level `get`/`post`
    # functions), so FastHTML's name-based method inference doesn't apply —
    # `.get`/`.post` are used explicitly to pin the HTTP method instead.
    @app.get("/")
    def get():
        return RedirectResponse("/fields", status_code=303)

    register_fields_routes(app, FieldRepository(conn))
    register_extraction_routes(
        app,
        FieldRepository(conn),
        ExtractionRunRepository(conn),
        pdf_extractor or PyMuPDF4LlmTextExtractor(),
        ner_extractor or LangExtractNerExtractor(),
        gold_yaml_path=gold_yaml_path,
    )
    return app


app = create_app(get_connection(DEFAULT_DB_PATH))


if __name__ == "__main__":
    # `app/main.py` lives inside the `app` package (run via `python -m app.main`),
    # so FastHTML's default module-stem guess ("main") would miss the package
    # prefix that uvicorn's reloader needs to re-import the app.
    serve(appname="app.main")
