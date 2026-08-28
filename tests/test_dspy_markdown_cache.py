from scripts.dspy_markdown_cache import get_markdown


class _FakePdfExtractor:
    def __init__(self, text: str):
        self.text = text
        self.call_count = 0

    def extract_text(self, pdf_bytes: bytes) -> str:
        self.call_count += 1
        return self.text


def test_get_markdown_extracts_and_caches_on_first_call(tmp_path):
    extractor = _FakePdfExtractor("# devis\ntexte extrait")

    result = get_markdown(
        "devis.pdf", b"fake-pdf-bytes", pdf_extractor=extractor, cache_dir=tmp_path
    )

    assert result == "# devis\ntexte extrait"
    assert extractor.call_count == 1
    assert (tmp_path / "devis.pdf.md").read_text(encoding="utf-8") == "# devis\ntexte extrait"


def test_get_markdown_reuses_cache_without_calling_extractor(tmp_path):
    extractor = _FakePdfExtractor("# devis\ntexte extrait")

    first = get_markdown(
        "devis.pdf", b"fake-pdf-bytes", pdf_extractor=extractor, cache_dir=tmp_path
    )
    second = get_markdown(
        "devis.pdf", b"fake-pdf-bytes", pdf_extractor=extractor, cache_dir=tmp_path
    )

    assert second == first
    assert extractor.call_count == 1


def test_get_markdown_creates_missing_cache_dir(tmp_path):
    extractor = _FakePdfExtractor("texte")
    cache_dir = tmp_path / "nested" / "cache"

    result = get_markdown(
        "devis.pdf", b"fake-pdf-bytes", pdf_extractor=extractor, cache_dir=cache_dir
    )

    assert result == "texte"
    assert cache_dir.exists()
