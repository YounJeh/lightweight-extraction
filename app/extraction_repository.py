import sqlite3

from app.models import ExtractionGrounding, ExtractionResult, ExtractionRun


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
        for result in results:
            result_cursor = self._conn.execute(
                "INSERT INTO extraction_results (run_id, field_title, value, source) "
                "VALUES (?, ?, ?, ?)",
                (run_id, result.field_title, result.value, result.source),
            )
            if result.page_number is not None and result.text_position is not None:
                grounding = ExtractionGrounding(
                    result_id=result_cursor.lastrowid,
                    page_number=result.page_number,
                    text_position=result.text_position,
                )
                self._conn.execute(
                    "INSERT INTO extraction_groundings "
                    "(result_id, page_number, text_position) VALUES (?, ?, ?)",
                    (grounding.result_id, grounding.page_number, grounding.text_position),
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
            "SELECT r.field_title, r.value, r.source, "
            "g.page_number AS page_number, g.text_position AS text_position "
            "FROM extraction_results r "
            "LEFT JOIN extraction_groundings g ON g.result_id = r.id "
            "WHERE r.run_id = ? ORDER BY r.id",
            (run_id,),
        ).fetchall()
        results = [
            ExtractionResult(
                field_title=r["field_title"],
                value=r["value"],
                source=r["source"],
                page_number=r["page_number"],
                text_position=r["text_position"],
            )
            for r in result_rows
        ]
        return ExtractionRun(
            id=row["id"], document_name=row["document_name"], results=results
        )
