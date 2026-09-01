"""Client pour un serveur NuExtract auto-hébergé (vLLM, API compatible
OpenAI) — pipeline de comparaison, jamais utilisé par l'app en production.

Voir specs/nuextract-pipeline-spike.md pour le contexte complet.
"""

import base64
import json
import os

import pymupdf
from openai import OpenAI

from app.models import ExtractionResult, Field
from app.tools import type_coercion

_RENDER_DPI = 150
_DEFAULT_MODEL = "numind/NuExtract3"


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


def _image_message_content(images: list[bytes]) -> list[dict]:
    return [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}"
            },
        }
        for image in images
    ]


def build_client(*, base_url: str | None = None, api_key: str | None = None) -> OpenAI:
    """`api_key` retombe sur `"EMPTY"` si absent — convention des serveurs
    vLLM auto-hébergés sans authentification (voir exemple officiel,
    specs/nuextract-pipeline-spike.md), le SDK `openai` refuse une clé
    vide/None."""
    return OpenAI(
        base_url=base_url or os.environ["NUEXTRACT_BASE_URL"],
        api_key=api_key or os.getenv("NUEXTRACT_API_KEY") or "EMPTY",
    )


def extract(
    pdf_bytes: bytes,
    fields: list[Field],
    *,
    client: OpenAI | None = None,
    model: str = _DEFAULT_MODEL,
) -> list[ExtractionResult]:
    """Extrait `fields` depuis `pdf_bytes` en un **seul** appel
    `chat/completions` — toutes les pages du document envoyées d'un coup,
    sans découpage en fenêtres (voir specs/nuextract-pipeline-spike.md,
    windowing repoussé tant que le corpus gold n'en a pas besoin).
    `client` injectable pour les tests offline (mock) ; par défaut construit
    depuis `NUEXTRACT_BASE_URL`/`NUEXTRACT_API_KEY`.

    `temperature=0` : on veut une recopie fidèle du document
    (`verbatim-string`), pas de variation créative — cohérent avec l'usage
    de "evidence" par le cadrage."""
    client = client or build_client()
    images = render_pdf_pages(pdf_bytes)
    template = build_template(fields)

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[{"role": "user", "content": _image_message_content(images)}],
        extra_body={"chat_template_kwargs": {"template": json.dumps(template)}},
    )
    return parse_response(response.choices[0].message.content, fields)
