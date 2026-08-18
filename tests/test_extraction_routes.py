import pytest
from starlette.testclient import TestClient

from app.extraction_repository import ExtractionRunRepository
from app.main import create_app
from app.models import ExtractionResult, FieldCreate
from app.repository import FieldRepository
from app.tools.mock_ner import MockNerExtractor
from app.tools.mock_pdf import MockPdfTextExtractor


@pytest.fixture
def client(db_conn):
    return TestClient(
        create_app(db_conn, MockPdfTextExtractor(), MockNerExtractor())
    )


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
    field_repo.create(FieldCreate(key="nom", title="Nom", definition="d", examples=[]))

    response = client.get("/extraction")

    assert "Nom" in response.text


def test_get_extraction_groups_fields_by_section_alphabetically(client, field_repo):
    field_repo.create(
        FieldCreate(key="a", title="A", definition="d", examples=[], section="Pénalité")
    )
    field_repo.create(
        FieldCreate(key="b", title="B", definition="d", examples=[], section="Assurances")
    )

    response = client.get("/extraction")

    assert response.text.index("Assurances") < response.text.index("Pénalité")


def test_get_extraction_puts_fields_without_section_in_autres_group(client, field_repo):
    field_repo.create(FieldCreate(key="a", title="A", definition="d", examples=[]))

    response = client.get("/extraction")

    assert "Autres" in response.text


def test_get_extraction_field_groups_are_closed_by_default(client, field_repo):
    field_repo.create(
        FieldCreate(key="a", title="A", definition="d", examples=[], section="Pénalité")
    )

    response = client.get("/extraction")

    assert "<details class=\"field-group\">" in response.text
    assert "<details open" not in response.text


def test_get_extraction_group_shows_toggle_buttons_and_initial_counter(client, field_repo):
    field_repo.create(
        FieldCreate(key="a", title="A", definition="d", examples=[], section="Pénalité")
    )
    field_repo.create(
        FieldCreate(key="b", title="B", definition="d", examples=[], section="Pénalité")
    )

    response = client.get("/extraction")

    assert "2/2 sélectionnés" in response.text
    assert 'data-select="all"' in response.text
    assert 'data-select="none"' in response.text


def test_get_extraction_fields_are_checked_by_default(client, field_repo):
    field_repo.create(
        FieldCreate(key="a", title="A", definition="d", examples=[], section="Pénalité")
    )

    response = client.get("/extraction")

    assert (
        '<input type="checkbox" name="field_ids" value="1" checked id="field-1">'
        in response.text
    )


def test_post_extraction_runs_mock_pipeline_and_persists_run(client, field_repo, run_repo):
    field = field_repo.create(
        FieldCreate(key="nom", title="Nom", definition="d", examples=[{"context": "Jean"}])
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
        FieldCreate(key="nom", title="Nom", definition="d", examples=[{"context": "Jean"}])
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


def test_extraction_result_page_shows_value_type(client, run_repo):
    run_repo.create_run(
        "doc.pdf",
        [ExtractionResult(field_title="Âge", value="30", source="mock", value_type="int")],
    )
    run = run_repo.list_runs()[0]

    response = client.get(f"/extraction/runs/{run.id}")

    assert "int" in response.text
    assert "result-value-error" not in response.text


def test_extraction_result_page_shows_typed_value_not_full_grounded_text(client, run_repo):
    run_repo.create_run(
        "doc.pdf",
        [
            ExtractionResult(
                field_title="Avance",
                value="15 % d'avance à la signature du contrat",
                source="langextract",
                value_type="int",
                typed_value="15",
            )
        ],
    )
    run = run_repo.list_runs()[0]

    response = client.get(f"/extraction/runs/{run.id}")

    assert 'class="result-value" title="15 % d\'avance à la signature du contrat">15</td>' in response.text


def test_extraction_result_page_flags_type_error_row(client, run_repo):
    run_repo.create_run(
        "doc.pdf",
        [
            ExtractionResult(
                field_title="Âge",
                value="inconnu",
                source="mock",
                value_type="int",
                type_error="« inconnu » n'est pas un entier valide",
            )
        ],
    )
    run = run_repo.list_runs()[0]

    response = client.get(f"/extraction/runs/{run.id}")

    assert "result-value-error" in response.text


def test_uploaded_pdf_bytes_are_never_persisted(client, field_repo, db_conn):
    field = field_repo.create(FieldCreate(key="nom", title="Nom", definition="d", examples=[]))

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
