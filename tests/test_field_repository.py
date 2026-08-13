import pytest

from app.models import FieldCreate, FieldUpdate
from app.repository import FieldRepository


@pytest.fixture
def repo(db_conn):
    return FieldRepository(db_conn)


def test_create_and_get(repo):
    field = repo.create(
        FieldCreate(title="Nom", definition="Nom de la personne", examples=["Jean"])
    )
    assert field.id is not None
    assert repo.get(field.id) == field


def test_create_rejects_empty_title(repo):
    with pytest.raises(ValueError):
        repo.create(FieldCreate(title="   ", definition="x", examples=[]))


def test_list_all_returns_created_fields_in_order(repo):
    repo.create(FieldCreate(title="A", definition="a", examples=[]))
    repo.create(FieldCreate(title="B", definition="b", examples=[]))

    fields = repo.list_all()

    assert [f.title for f in fields] == ["A", "B"]


def test_update_modifies_field(repo):
    field = repo.create(FieldCreate(title="A", definition="a", examples=[]))

    updated = repo.update(
        field.id, FieldUpdate(title="A2", definition="a2", examples=["ex"])
    )

    assert updated.title == "A2"
    assert updated.definition == "a2"
    assert updated.examples == ["ex"]


def test_update_rejects_empty_title(repo):
    field = repo.create(FieldCreate(title="A", definition="a", examples=[]))
    with pytest.raises(ValueError):
        repo.update(field.id, FieldUpdate(title=" ", definition="a", examples=[]))


def test_delete_removes_field(repo):
    field = repo.create(FieldCreate(title="A", definition="a", examples=[]))

    repo.delete(field.id)

    assert repo.get(field.id) is None


def test_get_missing_returns_none(repo):
    assert repo.get(9999) is None
