from starlette.testclient import TestClient

from app.main import create_app


def test_root_responds_ok(db_conn):
    client = TestClient(create_app(db_conn))
    response = client.get("/")
    assert response.status_code == 200
