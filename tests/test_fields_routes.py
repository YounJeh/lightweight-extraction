import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.models import FieldCreate
from app.repository import FieldRepository


@pytest.fixture
def client(db_conn):
    return TestClient(create_app(db_conn))


@pytest.fixture
def repo(db_conn):
    return FieldRepository(db_conn)


def test_get_fields_lists_existing_fields(client, repo):
    repo.create(FieldCreate(title="Nom", definition="Nom de la personne", examples=["Jean"]))

    response = client.get("/fields")

    assert response.status_code == 200
    assert "Nom" in response.text
    assert "Nom de la personne" in response.text


def test_get_fields_shows_empty_state_when_no_fields(client):
    response = client.get("/fields")

    assert response.status_code == 200
    assert "Aucun champ" in response.text


def test_post_fields_creates_a_field_and_redirects(client, repo):
    response = client.post(
        "/fields",
        data={"title": "Date", "definition": "Une date", "examples": "01/01/2026\n02/02/2026"},
    )

    assert response.status_code == 200  # TestClient follows the 303 redirect by default
    fields = repo.list_all()
    assert len(fields) == 1
    assert fields[0].title == "Date"
    assert fields[0].examples == ["01/01/2026", "02/02/2026"]


def test_post_fields_update_modifies_field(client, repo):
    field = repo.create(FieldCreate(title="A", definition="a", examples=[]))

    client.post(
        f"/fields/{field.id}/update",
        data={"title": "A2", "definition": "a2", "examples": "ex1"},
    )

    updated = repo.get(field.id)
    assert updated.title == "A2"
    assert updated.definition == "a2"
    assert updated.examples == ["ex1"]


def test_post_fields_delete_removes_field(client, repo):
    field = repo.create(FieldCreate(title="A", definition="a", examples=[]))

    client.post(f"/fields/{field.id}/delete")

    assert repo.get(field.id) is None
