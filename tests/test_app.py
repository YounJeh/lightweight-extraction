from starlette.testclient import TestClient

from app.main import create_app


def test_root_redirects_to_fields(db_conn):
    client = TestClient(create_app(db_conn))
    response = client.get("/")
    assert response.status_code == 200  # TestClient follows the 303 redirect
    assert response.request.url.path == "/fields"


def test_stylesheet_link_is_cache_busted(db_conn):
    # Sans version en query string, un navigateur qui a déjà chargé la page
    # garde le CSS en cache après une modification de static/style.css et ne
    # le recharge qu'au hard-refresh.
    client = TestClient(create_app(db_conn))
    response = client.get("/fields")
    assert 'href="/static/style.css?v=' in response.text
