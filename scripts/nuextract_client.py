"""Client pour un serveur NuExtract auto-hébergé (vLLM, API compatible
OpenAI) — pipeline de comparaison, jamais utilisé par l'app en production.

Voir specs/nuextract-pipeline-spike.md pour le contexte complet.
"""

import json

import pymupdf

from app.models import ExtractionResult, Field
from app.tools import type_coercion

_RENDER_DPI = 150


def render_pdf_pages(pdf_bytes: bytes, *, dpi: int = _RENDER_DPI) -> list[bytes]:
    """Rend chaque page du PDF en PNG (une image par page, dans l'ordre du
    document). NuExtract ne prend pas de PDF en entrée directement — ses
    exemples officiels attendent des images (voir specs/nuextract-pipeline-spike.md,
    section Tech Stack)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]
    finally:
        doc.close()


def build_template(fields: list[Field]) -> dict[str, str]:
    """Template NuExtract : un champ JSON plat par `Field.key`, toujours
    typé `"verbatim-string"` — un seul type pour tous les `FieldType` de
    l'app (pas de schéma imbriqué `{value, evidence}` par champ, non
    confirmé dans la doc publique de NuExtract). La coercion vers le type
    de l'app se fait ensuite côté client, via `type_coercion.validate`,
    comme pour un champ LangExtract sans `attributes['value']` (voir
    `_typed_value`, `app/tools/ner_langextract.py`)."""
    return {field.key: "verbatim-string" for field in fields}


def parse_response(content: str, fields: list[Field]) -> list[ExtractionResult]:
    """Convertit le JSON plat renvoyé par NuExtract (`{field.key: texte
    verbatim}`) en `ExtractionResult`, un par champ demandé — y compris les
    champs absents du JSON ou à valeur vide, avec `value=""` plutôt qu'une
    absence silencieuse (même convention que `LangExtractNerExtractor`,
    voir choix_techniques.md § "Export vers le gold dataset")."""
    parsed = json.loads(content)
    results = []
    for field in fields:
        raw = parsed.get(field.key)
        raw_value = str(raw).strip() if raw else ""
        if not raw_value:
            results.append(
                ExtractionResult(
                    field_title=field.title, value="", source="nuextract", value_type=field.type
                )
            )
            continue
        results.append(
            ExtractionResult(
                field_title=field.title,
                value=raw_value,
                source="nuextract",
                value_type=field.type,
                typed_value=raw_value,
                type_error=type_coercion.validate(raw_value, field.type),
            )
        )
    return results
