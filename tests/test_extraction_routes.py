import pytest
from starlette.testclient import TestClient

from app.extraction_repository import ExtractionRunRepository
from app.main import create_app
from app.models import FieldCreate
from app.repository import FieldRepository


@pytest.fixture
def client(db_conn):
    return TestClient(create_app(db_conn))


@pytest.fixture
def field_repo(db_conn):
    return FieldRepository(db_conn)


@pytest.fixture
def run_repo(db_conn):
    return ExtractionRunRepository(db_conn)


def _upload(client, field_ids, filename="doc.pdf"):
    data = {"field_ids": [str(fid) for fid in field_ids]}
    files = {"pdf": (filename, b"%PDF-1.4 fake content", "application/pdf")}
    return client.post("/extraction", data=data, files=files)


def test_get_extraction_shows_empty_state_without_fields(client):
    response = client.get("/extraction")

    assert response.status_code == 200
    assert "Aucun champ disponible" in response.text


def test_get_extraction_lists_available_fields(client, field_repo):
    field_repo.create(FieldCreate(title="Nom", definition="d", examples=[]))

    response = client.get("/extraction")

    assert "Nom" in response.text


def test_post_extraction_runs_mock_pipeline_and_persists_run(client, field_repo, run_repo):
    field = field_repo.create(
        FieldCreate(title="Nom", definition="d", examples=["Jean"])
    )

    response = _upload(client, [field.id])

    assert response.status_code == 200  # TestClient follows the 303 redirect
    runs = run_repo.list_runs()
    assert len(runs) == 1
    assert runs[0].document_name == "doc.pdf"
    assert len(runs[0].results) == 1
    assert runs[0].results[0].field_title == "Nom"
    assert runs[0].results[0].value == "Jean"
    assert runs[0].results[0].source == "mock"


def test_post_extraction_result_page_shows_mock_badge(client, field_repo):
    field = field_repo.create(
        FieldCreate(title="Nom", definition="d", examples=["Jean"])
    )

    response = _upload(client, [field.id])

    assert "Jean" in response.text
    assert "mock" in response.text


def test_post_extraction_with_no_fields_selected_persists_empty_results(
    client, run_repo
):
    _upload(client, [])

    runs = run_repo.list_runs()
    assert len(runs) == 1
    assert runs[0].results == []


def test_get_extraction_run_is_consultable_after_creation(client, run_repo):
    _upload(client, [])
    run = run_repo.list_runs()[0]

    response = client.get(f"/extraction/runs/{run.id}")

    assert response.status_code == 200
    assert "doc.pdf" in response.text


def test_uploaded_pdf_bytes_are_never_persisted(client, field_repo, db_conn):
    field = field_repo.create(FieldCreate(title="Nom", definition="d", examples=[]))

    _upload(client, [field.id])

    tables = {
        row["name"]
        for row in db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in tables:
        columns = [r["name"] for r in db_conn.execute(f"PRAGMA table_info({table})")]
        assert "pdf" not in columns and "content" not in columns and "bytes" not in columns


def test_post_extraction_rejects_non_pdf_file_without_crashing(client, run_repo):
    files = {"pdf": ("doc.txt", b"not a pdf", "text/plain")}

    response = client.post("/extraction", data={}, files=files)

    assert response.status_code == 200
    assert "Erreur" in response.text
    assert run_repo.list_runs() == []


def test_extraction_page_links_to_fields_page(client):
    response = client.get("/extraction")

    assert 'href="/fields"' in response.text
