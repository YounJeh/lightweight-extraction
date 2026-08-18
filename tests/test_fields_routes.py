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
    repo.create(
        FieldCreate(
            key="nom",
            title="Nom",
            definition="Nom de la personne",
            examples=[{"context": "Jean"}],
        )
    )

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
        data={
            "key": "date",
            "title": "Date",
            "definition": "Une date",
            "examples": "01/01/2026\n02/02/2026",
        },
    )

    assert response.status_code == 200  # TestClient follows the 303 redirect by default
    fields = repo.list_all()
    assert len(fields) == 1
    assert fields[0].title == "Date"
    assert [e.context for e in fields[0].examples] == ["01/01/2026", "02/02/2026"]


def test_post_fields_without_type_defaults_to_text(client, repo):
    client.post(
        "/fields", data={"key": "nom", "title": "Nom", "definition": "d", "examples": ""}
    )

    assert repo.list_all()[0].type == "text"


def test_post_fields_creates_field_with_chosen_type(client, repo):
    client.post(
        "/fields",
        data={"key": "age", "title": "Âge", "definition": "d", "examples": "", "type": "int"},
    )

    assert repo.list_all()[0].type == "int"


def test_get_fields_shows_selected_type_for_existing_field(client, repo):
    repo.create(FieldCreate(key="date", title="Date", definition="d", examples=[], type="date"))

    response = client.get("/fields")

    assert '<option value="date" selected>Date</option>' in response.text


def test_post_fields_update_modifies_field(client, repo):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))

    client.post(
        f"/fields/{field.id}/update",
        data={"key": "a", "title": "A2", "definition": "a2", "examples": "ex1"},
    )

    updated = repo.get(field.id)
    assert updated.title == "A2"
    assert updated.definition == "a2"
    assert [e.context for e in updated.examples] == ["ex1"]


def test_post_fields_update_changes_type(client, repo):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))

    client.post(
        f"/fields/{field.id}/update",
        data={"key": "a", "title": "A", "definition": "a", "examples": "", "type": "bool"},
    )

    assert repo.get(field.id).type == "bool"


def test_post_fields_delete_removes_field(client, repo):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))

    client.post(f"/fields/{field.id}/delete")

    assert repo.get(field.id) is None


def test_post_fields_with_blank_title_shows_error_without_crashing(client, repo):
    response = client.post(
        "/fields", data={"key": "k", "title": "   ", "definition": "d", "examples": ""}
    )

    assert response.status_code == 200
    assert "Erreur" in response.text
    assert repo.list_all() == []


def test_post_fields_update_with_blank_title_shows_error_without_crashing(
    client, repo
):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))

    response = client.post(
        f"/fields/{field.id}/update",
        data={"key": "a", "title": " ", "definition": "d", "examples": ""},
    )

    assert response.status_code == 200
    assert "Erreur" in response.text
    assert repo.get(field.id).title == "A"  # unchanged


def test_fields_page_links_to_extraction_page(client):
    response = client.get("/fields")

    assert 'href="/extraction"' in response.text
