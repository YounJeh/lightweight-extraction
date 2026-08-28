"""Cache disque du texte markdown extrait d'un PDF, par `source_file` — pour
que le script d'optimisation de prompts DSPy (`scripts/dspy_prompt_tuning.py`)
n'ait pas à refaire le PDF -> markdown (OCR compris) à chaque essai de
candidat. Même convention que `scripts/_ocr_tuning_cache/` dans
`scripts/validate_ocr_tuning.py` : fichiers plats par `source_file`, pas
d'invalidation par contenu — voir tasks/plan-dspy-prompt-tuning.md.
"""

from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / "_dspy_markdown_cache"


def get_markdown(
    source_file: str,
    pdf_bytes: bytes,
    *,
    pdf_extractor: Any,
    cache_dir: Path = CACHE_DIR,
) -> str:
    """Texte markdown pour `source_file`, depuis le cache si présent, sinon
    extrait via `pdf_extractor.extract_text(pdf_bytes)` puis mis en cache."""
    cache_path = cache_dir / f"{source_file}.md"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    text = pdf_extractor.extract_text(pdf_bytes)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text
