import pytest

from app.config import load_env
from app.db import get_connection, init_db

load_env()


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_db(conn)
    yield conn
    conn.close()
