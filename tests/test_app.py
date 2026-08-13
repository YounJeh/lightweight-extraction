from starlette.testclient import TestClient

from app.main import create_app


def test_root_redirects_to_fields(db_conn):
    client = TestClient(create_app(db_conn))
    response = client.get("/")
    assert response.status_code == 200  # TestClient follows the 303 redirect
    assert response.request.url.path == "/fields"
