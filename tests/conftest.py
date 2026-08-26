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


@pytest.fixture(autouse=True, scope="session")
def _no_real_basic_auth_in_tests():
    """Même raisonnement que `_no_real_langfuse_in_tests` : le `.env` local
    contient de vrais identifiants Basic Auth (nécessaires pour créer les
    secrets Cloud Run), qui casseraient tous les tests de routes n'envoyant
    pas de credentials si on les laissait fuiter dans os.environ. Seuls les
    tests de `tests/test_auth.py` doivent voir ces variables — ils les
    positionnent eux-mêmes via `monkeypatch.setenv`."""
    os.environ.pop("BASIC_AUTH_USER", None)
    os.environ.pop("BASIC_AUTH_PASSWORD", None)


@pytest.fixture
def db_conn(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    init_db(conn)
    yield conn
    conn.close()
