import sqlite3

from app.models import ExtractionResult, ExtractionRun


class ExtractionRunRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create_run(
        self, document_name: str, results: list[ExtractionResult]
    ) -> ExtractionRun:
        cursor = self._conn.execute(
            "INSERT INTO extraction_runs (document_name) VALUES (?)",
            (document_name,),
        )
        run_id = cursor.lastrowid
        self._conn.executemany(
            "INSERT INTO extraction_results (run_id, field_title, value, source) "
            "VALUES (?, ?, ?, ?)",
            [(run_id, r.field_title, r.value, r.source) for r in results],
        )
        self._conn.commit()
        return self.get_run(run_id)

    def list_runs(self) -> list[ExtractionRun]:
        rows = self._conn.execute(
            "SELECT id FROM extraction_runs ORDER BY id"
        ).fetchall()
        return [self.get_run(row["id"]) for row in rows]

    def get_run(self, run_id: int) -> ExtractionRun | None:
        row = self._conn.execute(
            "SELECT id, document_name FROM extraction_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        result_rows = self._conn.execute(
            "SELECT field_title, value, source FROM extraction_results "
            "WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        results = [
            ExtractionResult(
                field_title=r["field_title"], value=r["value"], source=r["source"]
            )
            for r in result_rows
        ]
        return ExtractionRun(
            id=row["id"], document_name=row["document_name"], results=results
        )
