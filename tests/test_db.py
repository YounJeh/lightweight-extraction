from app.db import get_connection, init_db


def test_init_db_creates_expected_tables(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)

    init_db(conn)

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "fields",
        "extraction_runs",
        "extraction_results",
        "extraction_groundings",
    } <= tables
    conn.close()


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)

    init_db(conn)
    init_db(conn)  # must not raise on a schema that already exists

    conn.close()


def test_db_conn_fixture_uses_temp_path_not_dev_db(db_conn, tmp_path):
    row = db_conn.execute("SELECT file FROM pragma_database_list WHERE name='main'").fetchone()
    assert str(tmp_path) in row["file"]


def test_init_db_adds_type_column_to_pre_existing_fields_table(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    # Simule une DB créée avant l'ajout de la colonne `type`.
    conn.execute(
        "CREATE TABLE fields (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT NOT NULL, definition TEXT NOT NULL, "
        "examples TEXT NOT NULL DEFAULT '[]')"
    )
    conn.execute(
        "INSERT INTO fields (title, definition, examples) VALUES (?, ?, ?)",
        ("Titre existant", "Définition", "[]"),
    )
    conn.commit()

    init_db(conn)
    init_db(conn)  # doit rester idempotent

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(fields)")}
    assert "type" in columns
    row = conn.execute("SELECT type FROM fields WHERE title = ?", ("Titre existant",)).fetchone()
    assert row["type"] == "text"
    conn.close()
