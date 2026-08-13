_FAKE_TEXT = (
    "Ceci est un texte simulé, indépendant du contenu réel du PDF uploadé. "
    "Il sert uniquement à valider le flux d'upload et d'extraction du mock."
)


class MockPdfTextExtractor:
    """Simule PyMuPDF4LLM : renvoie toujours le même texte, quel que soit le fichier."""

    def extract_text(self, pdf_bytes: bytes) -> str:
        return _FAKE_TEXT
