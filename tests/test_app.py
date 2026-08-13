from starlette.testclient import TestClient

from app.main import app


def test_root_responds_ok():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
