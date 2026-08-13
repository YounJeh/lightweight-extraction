import sqlite3

from fasthtml.common import Titled, fast_app, serve

from app.db import DEFAULT_DB_PATH, get_connection, init_db
from app.extraction_repository import ExtractionRunRepository
from app.repository import FieldRepository
from app.routes.extraction import register_extraction_routes
from app.routes.fields import register_fields_routes
from app.tools.mock_ner import MockNerExtractor
from app.tools.mock_pdf import MockPdfTextExtractor


def create_app(conn: sqlite3.Connection):
    init_db(conn)
    app, _ = fast_app()

    # Route handlers below are nested closures (not top-level `get`/`post`
    # functions), so FastHTML's name-based method inference doesn't apply —
    # `.get`/`.post` are used explicitly to pin the HTTP method instead.
    @app.get("/")
    def get():
        return Titled("Lightweight Extraction")

    register_fields_routes(app, FieldRepository(conn))
    register_extraction_routes(
        app,
        FieldRepository(conn),
        ExtractionRunRepository(conn),
        MockPdfTextExtractor(),
        MockNerExtractor(),
    )
    return app


app = create_app(get_connection(DEFAULT_DB_PATH))


if __name__ == "__main__":
    # `app/main.py` lives inside the `app` package (run via `python -m app.main`),
    # so FastHTML's default module-stem guess ("main") would miss the package
    # prefix that uvicorn's reloader needs to re-import the app.
    serve(appname="app.main")
