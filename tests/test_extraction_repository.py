import pytest

from app.extraction_repository import ExtractionRunRepository
from app.models import ExtractionResult


@pytest.fixture
def repo(db_conn):
    return ExtractionRunRepository(db_conn)


def test_create_run_persists_document_name_and_results(repo):
    results = [
        ExtractionResult(field_title="Nom", value="Jean", source="mock"),
        ExtractionResult(field_title="Date", value="01/01/2026", source="mock"),
    ]

    run = repo.create_run("document.pdf", results)

    assert run.id is not None
    assert run.document_name == "document.pdf"
    assert run.results == results


def test_get_run_returns_persisted_run(repo):
    created = repo.create_run(
        "doc.pdf", [ExtractionResult(field_title="A", value="v", source="mock")]
    )

    assert repo.get_run(created.id) == created


def test_get_run_missing_returns_none(repo):
    assert repo.get_run(9999) is None


def test_list_runs_returns_all_runs_in_order(repo):
    repo.create_run("a.pdf", [])
    repo.create_run("b.pdf", [])

    runs = repo.list_runs()

    assert [run.document_name for run in runs] == ["a.pdf", "b.pdf"]


def test_create_run_with_no_results(repo):
    run = repo.create_run("empty.pdf", [])
    assert run.results == []


def test_grounding_round_trips_through_get_run(repo):
    result = ExtractionResult(
        field_title="Titre",
        value="Contrat de bail",
        source="langextract",
        page_number=2,
        text_position="...le Contrat de bail signé...",
    )

    created = repo.create_run("doc.pdf", [result])
    fetched = repo.get_run(created.id)

    assert fetched.results == [result]


def test_value_type_and_type_error_round_trip_through_get_run(repo):
    valid = ExtractionResult(
        field_title="Âge", value="30", source="langextract", value_type="int"
    )
    invalid = ExtractionResult(
        field_title="Date",
        value="pas une date",
        source="langextract",
        value_type="date",
        type_error="valeur non convertible en date",
    )

    created = repo.create_run("doc.pdf", [valid, invalid])
    fetched = repo.get_run(created.id)

    assert fetched.results == [valid, invalid]


def test_mixed_grounded_and_ungrounded_results_round_trip(repo):
    grounded = ExtractionResult(
        field_title="Titre",
        value="Contrat",
        source="langextract",
        page_number=1,
        text_position="...Contrat...",
    )
    ungrounded = ExtractionResult(field_title="Nom", value="Jean", source="mock")

    created = repo.create_run("doc.pdf", [grounded, ungrounded])
    fetched = repo.get_run(created.id)

    assert fetched.results == [grounded, ungrounded]
