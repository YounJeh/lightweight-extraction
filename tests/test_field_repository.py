import pytest

from app.models import FieldCreate, FieldUpdate
from app.repository import FieldRepository


@pytest.fixture
def repo(db_conn):
    return FieldRepository(db_conn)


def test_create_and_get(repo):
    field = repo.create(
        FieldCreate(
            key="nom",
            title="Nom",
            definition="Nom de la personne",
            examples=[{"context": "Jean"}],
        )
    )
    assert field.id is not None
    assert repo.get(field.id) == field


def test_create_defaults_to_text_type(repo):
    field = repo.create(FieldCreate(key="nom", title="Nom", definition="Nom", examples=[]))
    assert field.type == "text"


def test_create_persists_explicit_type(repo):
    field = repo.create(
        FieldCreate(
            key="age", title="Âge", definition="Âge en années", examples=[], type="int"
        )
    )
    assert repo.get(field.id).type == "int"


def test_update_changes_type(repo):
    field = repo.create(
        FieldCreate(key="date", title="Date", definition="d", examples=[])
    )

    updated = repo.update(
        field.id,
        FieldUpdate(key="date", title="Date", definition="d", examples=[], type="date"),
    )

    assert updated.type == "date"


def test_create_rejects_empty_title(repo):
    with pytest.raises(ValueError):
        repo.create(FieldCreate(key="k", title="   ", definition="x", examples=[]))


def test_create_rejects_empty_key(repo):
    with pytest.raises(ValueError):
        repo.create(FieldCreate(key="   ", title="A", definition="x", examples=[]))


def test_create_rejects_duplicate_key(repo):
    repo.create(FieldCreate(key="k1", title="A", definition="a", examples=[]))
    with pytest.raises(ValueError):
        repo.create(FieldCreate(key="k1", title="B", definition="b", examples=[]))


def test_list_all_returns_created_fields_in_order(repo):
    repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))
    repo.create(FieldCreate(key="b", title="B", definition="b", examples=[]))

    fields = repo.list_all()

    assert [f.title for f in fields] == ["A", "B"]


def test_update_modifies_field(repo):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))

    updated = repo.update(
        field.id,
        FieldUpdate(key="a", title="A2", definition="a2", examples=[{"context": "ex"}]),
    )

    assert updated.title == "A2"
    assert updated.definition == "a2"
    assert updated.examples[0].context == "ex"


def test_update_rejects_empty_title(repo):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))
    with pytest.raises(ValueError):
        repo.update(field.id, FieldUpdate(key="a", title=" ", definition="a", examples=[]))


def test_delete_removes_field(repo):
    field = repo.create(FieldCreate(key="a", title="A", definition="a", examples=[]))

    repo.delete(field.id)

    assert repo.get(field.id) is None


def test_get_missing_returns_none(repo):
    assert repo.get(9999) is None


def test_upsert_by_key_creates_when_key_is_new(repo):
    field = repo.upsert_by_key(
        FieldCreate(key="k1", title="A", definition="a", examples=[], section="S1")
    )
    assert field.key == "k1"
    assert repo.list_all() == [field]


def test_upsert_by_key_replaces_existing_field_entirely(repo):
    created = repo.upsert_by_key(
        FieldCreate(
            key="k1",
            title="A",
            definition="a",
            examples=[{"context": "ex1"}],
            section="S1",
            type="text",
        )
    )

    replaced = repo.upsert_by_key(
        FieldCreate(
            key="k1",
            title="A2",
            definition="a2",
            examples=[{"context": "ex2"}],
            section="S2",
            type="int",
        )
    )

    assert replaced.id == created.id
    assert replaced.title == "A2"
    assert replaced.definition == "a2"
    assert replaced.section == "S2"
    assert replaced.type == "int"
    assert replaced.examples[0].context == "ex2"
    assert len(repo.list_all()) == 1
