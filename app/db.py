import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    definition TEXT NOT NULL,
    section TEXT,
    examples TEXT NOT NULL DEFAULT '[]',
    type TEXT NOT NULL DEFAULT 'text'
);

CREATE TABLE IF NOT EXISTS extraction_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES extraction_runs(id),
    field_title TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'mock',
    value_type TEXT,
    typed_value TEXT,
    type_error TEXT
);

CREATE TABLE IF NOT EXISTS extraction_groundings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL REFERENCES extraction_results(id),
    page_number INTEGER NOT NULL,
    text_position TEXT NOT NULL
);
"""


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: Starlette runs sync route handlers in a worker
    # thread pool, so the connection created at app startup (main thread) must
    # remain usable from those worker threads. Safe here since this is a
    # single-user local app with no concurrent writers.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, column_def: str
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # ALTER TABLE ponctuel pour les DB créées avant l'ajout de ces colonnes —
    # CREATE TABLE IF NOT EXISTS ne les ajoute pas rétroactivement.
    _add_column_if_missing(conn, "fields", "type", "TEXT NOT NULL DEFAULT 'text'")
    _add_column_if_missing(conn, "fields", "key", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "fields", "section", "TEXT")
    _add_column_if_missing(conn, "extraction_results", "value_type", "TEXT")
    _add_column_if_missing(conn, "extraction_results", "typed_value", "TEXT")
    _add_column_if_missing(conn, "extraction_results", "type_error", "TEXT")
    # Index séparé plutôt qu'une contrainte UNIQUE inline sur `key` : SQLite
    # ne permet pas d'ajouter une contrainte UNIQUE via ALTER TABLE ADD
    # COLUMN sur une table existante, un index fonctionne dans les deux cas.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_fields_key ON fields(key)")
    conn.commit()
