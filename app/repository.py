import json
import sqlite3

from app.models import Field, FieldCreate, FieldUpdate


class FieldRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, data: FieldCreate) -> Field:
        title = self._require_title(data.title)
        cursor = self._conn.execute(
            "INSERT INTO fields (title, definition, examples, type) VALUES (?, ?, ?, ?)",
            (title, data.definition, json.dumps(data.examples), data.type),
        )
        self._conn.commit()
        return self.get(cursor.lastrowid)

    def list_all(self) -> list[Field]:
        rows = self._conn.execute("SELECT * FROM fields ORDER BY id").fetchall()
        return [self._row_to_field(row) for row in rows]

    def get(self, field_id: int) -> Field | None:
        row = self._conn.execute(
            "SELECT * FROM fields WHERE id = ?", (field_id,)
        ).fetchone()
        return self._row_to_field(row) if row else None

    def update(self, field_id: int, data: FieldUpdate) -> Field | None:
        title = self._require_title(data.title)
        self._conn.execute(
            "UPDATE fields SET title = ?, definition = ?, examples = ?, type = ? WHERE id = ?",
            (title, data.definition, json.dumps(data.examples), data.type, field_id),
        )
        self._conn.commit()
        return self.get(field_id)

    def delete(self, field_id: int) -> None:
        self._conn.execute("DELETE FROM fields WHERE id = ?", (field_id,))
        self._conn.commit()

    @staticmethod
    def _require_title(title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("title must not be empty")
        return title

    @staticmethod
    def _row_to_field(row: sqlite3.Row) -> Field:
        return Field(
            id=row["id"],
            title=row["title"],
            definition=row["definition"],
            examples=json.loads(row["examples"]),
            type=row["type"],
        )
