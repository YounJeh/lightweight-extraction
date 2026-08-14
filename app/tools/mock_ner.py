from app.models import ExtractionResult, Field


class MockNerExtractor:
    """Simule LangExtract : une valeur factice déterministe par champ, sans
    grounding réel dans le texte (cohérent avec un texte source lui-même simulé)."""

    def extract(self, text: str, fields: list[Field]) -> list[ExtractionResult]:
        return [self._mock_result(field) for field in fields]

    @staticmethod
    def _mock_result(field: Field) -> ExtractionResult:
        value = (
            field.examples[0]
            if field.examples
            else f"Valeur simulée pour « {field.title} »"
        )
        return ExtractionResult(
            field_title=field.title, value=value, source="mock", value_type=field.type
        )
