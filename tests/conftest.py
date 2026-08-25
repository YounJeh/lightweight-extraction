import os

import pytest

from app.config import load_env
from app.db import get_connection, init_db

load_env()


@pytest.fixture(autouse=True, scope="session")
def _no_real_langfuse_in_tests():
    """La suite de tests ne doit jamais envoyer de vraies traces Langfuse,
    même si le .env local du développeur contient de vraies clés (pour faire
    tourner l'app réelle) — build_tracer() doit toujours retomber sur
    NoOpTracer ici. Un simple pop() au niveau module ne suffit pas : importer
    app.main (fait par plusieurs modules de test au moment de la collecte)
    appelle à nouveau load_env(), qui réinjecte les clés depuis .env puisque
    le garde ("if key not in os.environ") ne voit plus le pop précédent.
    Cette fixture session tourne après la phase de collecte (tous les imports
    déjà faits) et juste avant le premier test — dernier mot garanti."""
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_db(conn)
    yield conn
    conn.close()
