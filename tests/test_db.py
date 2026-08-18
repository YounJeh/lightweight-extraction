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


def test_init_db_adds_key_and_section_columns_to_pre_existing_fields_table(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    # Simule une DB créée avant l'ajout des colonnes `key`/`section`.
    conn.execute(
        "CREATE TABLE fields (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT NOT NULL, definition TEXT NOT NULL, "
        "examples TEXT NOT NULL DEFAULT '[]', type TEXT NOT NULL DEFAULT 'text')"
    )
    conn.execute(
        "INSERT INTO fields (title, definition, examples) VALUES (?, ?, ?)",
        ("Titre existant", "Définition", "[]"),
    )
    conn.commit()

    init_db(conn)
    init_db(conn)  # doit rester idempotent

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(fields)")}
    assert {"key", "section"} <= columns
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(fields)")}
    assert "idx_fields_key" in indexes
    conn.close()


def test_init_db_creates_unique_index_on_fields_key(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_db(conn)

    conn.execute(
        "INSERT INTO fields (key, title, definition) VALUES ('k1', 'A', 'def')"
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO fields (key, title, definition) VALUES ('k1', 'B', 'def')"
        )
        conn.commit()
        raised = False
    except Exception:
        raised = True
    assert raised
    conn.close()


def test_init_db_migrates_pre_existing_table_with_multiple_fields(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    # Simule une DB pré-`key`/`section` avec plusieurs champs déjà en base —
    # sans backfill, ils hériteraient tous du même défaut '' et la création
    # de l'index unique sur `key` échouerait.
    conn.execute(
        "CREATE TABLE fields (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "title TEXT NOT NULL, definition TEXT NOT NULL, "
        "examples TEXT NOT NULL DEFAULT '[]', type TEXT NOT NULL DEFAULT 'text')"
    )
    conn.execute("INSERT INTO fields (title, definition) VALUES ('A', 'defA')")
    conn.execute("INSERT INTO fields (title, definition) VALUES ('B', 'defB')")
    conn.execute("INSERT INTO fields (title, definition) VALUES ('C', 'defC')")
    conn.commit()

    init_db(conn)  # ne doit pas lever d'IntegrityError
    init_db(conn)  # doit rester idempotent

    rows = conn.execute("SELECT id, key FROM fields ORDER BY id").fetchall()
    keys = [row["key"] for row in rows]
    assert len(keys) == len(set(keys))  # toutes uniques
    assert all(k for k in keys)  # aucune vide
    conn.close()


def test_init_db_adds_value_type_and_type_error_columns_to_pre_existing_results_table(
    tmp_path,
):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE extraction_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "document_name TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE extraction_results (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id INTEGER NOT NULL REFERENCES extraction_runs(id), "
        "field_title TEXT NOT NULL, value TEXT NOT NULL, "
        "source TEXT NOT NULL DEFAULT 'mock')"
    )
    conn.execute("INSERT INTO extraction_runs (document_name) VALUES ('doc.pdf')")
    conn.execute(
        "INSERT INTO extraction_results (run_id, field_title, value, source) "
        "VALUES (1, 'Titre', 'valeur', 'mock')"
    )
    conn.commit()

    init_db(conn)
    init_db(conn)  # doit rester idempotent

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(extraction_results)")}
    assert {"value_type", "typed_value", "type_error"} <= columns
    row = conn.execute(
        "SELECT value_type, typed_value, type_error FROM extraction_results "
        "WHERE field_title = 'Titre'"
    ).fetchone()
    assert row["value_type"] is None
    assert row["typed_value"] is None
    assert row["type_error"] is None
    conn.close()
