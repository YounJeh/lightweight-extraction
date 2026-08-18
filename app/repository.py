import json
import sqlite3

from app.models import Field, FieldCreate, FieldUpdate


class FieldRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, data: FieldCreate) -> Field:
        key, params = self._validated_params(data)
        try:
            cursor = self._conn.execute(
                "INSERT INTO fields (key, title, definition, section, examples, type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                params,
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"key already exists: {key}") from e
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
        key, params = self._validated_params(data)
        try:
            self._conn.execute(
                "UPDATE fields SET key = ?, title = ?, definition = ?, section = ?, "
                "examples = ?, type = ? WHERE id = ?",
                (*params, field_id),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"key already exists: {key}") from e
        self._conn.commit()
        return self.get(field_id)

    def upsert_by_key(self, data: FieldCreate) -> Field:
        """Crée le champ si `data.key` est inédit, sinon remplace
        entièrement title/definition/section/examples/type de la ligne
        existante (pas de fusion) — utilisé par l'import de fichier."""
        key, params = self._validated_params(data)
        self._conn.execute(
            "INSERT INTO fields (key, title, definition, section, examples, type) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "title = excluded.title, definition = excluded.definition, "
            "section = excluded.section, examples = excluded.examples, "
            "type = excluded.type",
            params,
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM fields WHERE key = ?", (key,)
        ).fetchone()
        return self._row_to_field(row)

    def delete(self, field_id: int) -> None:
        self._conn.execute("DELETE FROM fields WHERE id = ?", (field_id,))
        self._conn.commit()

    @classmethod
    def _validated_params(cls, data: FieldCreate | FieldUpdate) -> tuple[str, tuple]:
        key = cls._require_key(data.key)
        title = cls._require_title(data.title)
        params = (
            key,
            title,
            data.definition,
            data.section,
            cls._dump_examples(data.examples),
            data.type,
        )
        return key, params

    @staticmethod
    def _require_title(title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("title must not be empty")
        return title

    @staticmethod
    def _require_key(key: str) -> str:
        key = key.strip()
        if not key:
            raise ValueError("key must not be empty")
        return key

    @staticmethod
    def _dump_examples(examples: list) -> str:
        return json.dumps([e.model_dump() for e in examples])

    @staticmethod
    def _row_to_field(row: sqlite3.Row) -> Field:
        return Field(
            id=row["id"],
            key=row["key"],
            title=row["title"],
            definition=row["definition"],
            section=row["section"],
            examples=json.loads(row["examples"]),
            type=row["type"],
        )
