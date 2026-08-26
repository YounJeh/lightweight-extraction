import base64

from starlette.testclient import TestClient

from app.main import create_app


def _auth_header(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_no_auth_configured_allows_access(db_conn, monkeypatch):
    monkeypatch.delenv("BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("BASIC_AUTH_PASSWORD", raising=False)
    client = TestClient(create_app(db_conn))
    response = client.get("/fields")
    assert response.status_code == 200


def test_missing_credentials_rejected(db_conn, monkeypatch):
    monkeypatch.setenv("BASIC_AUTH_USER", "testuser")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "testpass")
    client = TestClient(create_app(db_conn))
    response = client.get("/fields")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Basic"


def test_wrong_credentials_rejected(db_conn, monkeypatch):
    monkeypatch.setenv("BASIC_AUTH_USER", "testuser")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "testpass")
    client = TestClient(create_app(db_conn))
    response = client.get("/fields", headers=_auth_header("testuser", "wrong"))
    assert response.status_code == 401


def test_correct_credentials_allowed(db_conn, monkeypatch):
    monkeypatch.setenv("BASIC_AUTH_USER", "testuser")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "testpass")
    client = TestClient(create_app(db_conn))
    response = client.get("/fields", headers=_auth_header("testuser", "testpass"))
    assert response.status_code == 200
