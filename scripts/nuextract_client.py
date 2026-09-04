"""Client pour un serveur NuExtract auto-hébergé (vLLM, API compatible
OpenAI) — pipeline de comparaison, jamais utilisé par l'app en production.

Voir specs/nuextract-pipeline-spike.md pour le contexte complet.
"""

import base64
import json
import os
import time
from typing import Callable

import openai
import pymupdf
from openai import OpenAI

from app.models import ExtractionResult, Field
from app.tools import type_coercion

_RENDER_DPI = 150
_DEFAULT_MODEL = "numind/NuExtract3"

# Un serveur Modal scale-to-zero (min_containers=0) renvoie "503 no
# upstreams available" immédiatement -- pas d'attente du cold-start --
# quand une requête arrive avant qu'un conteneur soit prêt. Retry avec
# backoff exponentiel plafonné plutôt qu'un échec immédiat ; couvre aussi
# une coupure de connexion transitoire pendant le démarrage. Pas de retry
# sur une erreur non transitoire (ex. 400 schéma invalide) -- seules ces
# deux exceptions sont ciblées.
#
# _MAX_RETRIES=8 (~155s de budget) s'est révélé insuffisant en réel :
# reproduit deux fois de suite sur le même document (data_test/OFR2603012513
# - ENTECH.pdf, "item 0" du gold), la 1ère tentative a épuisé les 8 retries
# en 503 persistant, la 2e a réussi après seulement 3 retries -- le
# cold-start est plus variable que les ~2-3 min observées au départ, pas
# un bug propre au document. Budget élargi à ~515s (20 tentatives, 19
# sleeps : 5+10+20+30x16), proche du startup_timeout=600 déjà configuré
# côté serveur (scripts/modal_nuextract_server.py) -- au-delà, Modal
# lui-même aurait abandonné le démarrage, continuer à retenter ne servirait
# à rien.
_RETRYABLE_EXCEPTIONS = (openai.InternalServerError, openai.APIConnectionError)
_MAX_RETRIES = 20
_INITIAL_BACKOFF_SECONDS = 5.0
_MAX_BACKOFF_SECONDS = 30.0

# Windowing (voir docs/ideas/nuextract-windowing.md) : un document de plus
# de _WINDOW_SIZE_PAGES pages est découpé en fenêtres glissantes plutôt
# qu'envoyé en un seul appel. Constantes dérivées d'un ratio observé en
# réel (~2000-2200 tokens/page, 3 échecs "context length exceeded" sur des
# documents de 12-14 pages contre une limite serveur de 16384 tokens) : 4
# pages ≈ 11000 tokens, marge confortable. Overlap de 1 page pour ne pas
# couper une valeur à cheval sur une frontière de page.
_WINDOW_SIZE_PAGES = 4
_WINDOW_OVERLAP_PAGES = 1


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


def build_template(fields: list[Field]) -> dict[str, dict[str, str]]:
    """Template NuExtract : un objet imbriqué `{value, evidence}` par
    `Field.key`, tous deux typés `"verbatim-string"` — un seul type pour
    tous les `FieldType` de l'app, la coercion vers le type de l'app se
    faisant ensuite côté client via `type_coercion.validate` (comme pour un
    champ LangExtract sans `attributes['value']`, voir `_typed_value`,
    `app/tools/ner_langextract.py`). NuExtract supporte les objets JSON
    imbriqués dans son template (voir le README à jour du repo
    numindai/nuextract, ex. `line_items`) : `evidence` porte la citation
    verbatim justifiant `value`, jamais typée/coercée elle-même."""
    return {
        field.key: {"value": "verbatim-string", "evidence": "verbatim-string"}
        for field in fields
    }


def parse_response(content: str, fields: list[Field]) -> list[ExtractionResult]:
    """Convertit le JSON imbriqué renvoyé par NuExtract (`{field.key:
    {"value": ..., "evidence": ...}}`) en `ExtractionResult`, un par champ
    demandé — y compris les champs absents du JSON ou à `value` vide, avec
    `value=""` et `evidence=None` plutôt qu'une absence silencieuse (même
    convention que `LangExtractNerExtractor`, voir choix_techniques.md §
    "Export vers le gold dataset"). `evidence` n'est peuplée que lorsque
    `value` l'est aussi -- une citation sans valeur associée n'a pas de
    sens pour ce champ."""
    parsed = json.loads(content)
    results = []
    for field in fields:
        raw = parsed.get(field.key)
        raw = raw if isinstance(raw, dict) else {}
        raw_value = str(raw.get("value") or "").strip()
        if not raw_value:
            results.append(
                ExtractionResult(
                    field_title=field.title, value="", source="nuextract", value_type=field.type
                )
            )
            continue
        raw_evidence = str(raw.get("evidence") or "").strip() or None
        results.append(
            ExtractionResult(
                field_title=field.title,
                value=raw_value,
                evidence=raw_evidence,
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


def _page_windows(
    page_count: int, *, size: int = _WINDOW_SIZE_PAGES, overlap: int = _WINDOW_OVERLAP_PAGES
) -> list[tuple[int, int]]:
    """Bornes `[start, end)` de chaque fenêtre de pages, avec chevauchement.
    Une seule fenêtre couvrant tout le document si `page_count <= size`
    (comportement d'avant le windowing, inchangé dans ce cas)."""
    if page_count <= size:
        return [(0, page_count)]
    step = size - overlap
    windows = []
    start = 0
    while start < page_count:
        end = min(start + size, page_count)
        windows.append((start, end))
        if end == page_count:
            break
        start += step
    return windows


def _merge_window_results(
    window_results: list[list[ExtractionResult]],
) -> list[ExtractionResult]:
    """Fusionne les résultats de plusieurs fenêtres, par champ : la
    **première fenêtre (dans l'ordre du document) qui renvoie une valeur
    non vide gagne** — pas d'arbitrage LLM cross-fenêtre pour cette version
    (voir docs/ideas/nuextract-windowing.md). Une seule fenêtre (cas
    courant, document court) traverse cette fonction sans effet : chaque
    champ n'a qu'un candidat, retenu tel quel."""
    merged: dict[str, ExtractionResult] = {}
    for results in window_results:
        for result in results:
            existing = merged.get(result.field_title)
            if existing is not None and existing.value:
                continue
            if existing is None or result.value:
                merged[result.field_title] = result
    return list(merged.values())


def _create_completion_with_retries(
    client: OpenAI,
    *,
    sleep: Callable[[float], None] | None = None,
    on_retry: Callable[[float], None] | None = None,
    **kwargs,
):
    """`on_retry(delay)` est appelé après chaque `sleep(delay)` -- pas
    avant -- pour que `delay` reflète le temps réellement attendu (voir
    docs/ideas/nuextract-cold-start-latency.md). Permet à l'appelant
    d'accumuler un temps d'attente cumulé (essentiellement du cold-start
    serveur, mais pas exclusivement -- toute tentative retentée déclenche
    ce callback) sans changer le type de retour de cette fonction.

    `sleep` résolu à l'intérieur (pas `sleep=time.sleep` en défaut) pour
    rester patchable via `monkeypatch` même à travers `extract()`, qui ne
    l'expose pas lui-même -- un défaut lié à l'import fige la référence
    une fois pour toutes, invisible à un monkeypatch fait après coup."""
    sleep = sleep or time.sleep
    delay = _INITIAL_BACKOFF_SECONDS
    for attempt in range(_MAX_RETRIES):
        try:
            return client.chat.completions.create(**kwargs)
        except _RETRYABLE_EXCEPTIONS:
            if attempt == _MAX_RETRIES - 1:
                raise
            sleep(delay)
            if on_retry is not None:
                on_retry(delay)
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)


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
    on_retry: Callable[[float], None] | None = None,
) -> list[ExtractionResult]:
    """Extrait `fields` depuis `pdf_bytes` via un ou plusieurs appels
    `chat/completions` selon le nombre de pages : un seul appel si le
    document tient dans `_WINDOW_SIZE_PAGES`, sinon découpage en fenêtres
    glissantes avec chevauchement (`_page_windows`) — transparent pour
    l'appelant, signature et type de retour inchangés (voir
    docs/ideas/nuextract-windowing.md). Les résultats de plusieurs fenêtres
    sont fusionnés par `_merge_window_results` (1ère valeur non vide
    gagne).

    `client` injectable pour les tests offline (mock) ; par défaut construit
    depuis `NUEXTRACT_BASE_URL`/`NUEXTRACT_API_KEY`. `on_retry`, transmis
    tel quel à `_create_completion_with_retries` pour **chaque** fenêtre —
    un document à plusieurs fenêtres peut donc accumuler plusieurs appels
    du callback, un par tentative retentée, toutes fenêtres confondues
    (voir docs/ideas/nuextract-cold-start-latency.md).

    `temperature=0` : on veut une recopie fidèle du document
    (`verbatim-string`), pas de variation créative — cohérent avec
    `evidence`, qui doit être une citation verbatim, pas une paraphrase."""
    client = client or build_client()
    images = render_pdf_pages(pdf_bytes)
    template = build_template(fields)
    template_json = json.dumps(template)

    window_results = []
    for start, end in _page_windows(len(images)):
        response = _create_completion_with_retries(
            client,
            on_retry=on_retry,
            model=model,
            temperature=0,
            messages=[{"role": "user", "content": _image_message_content(images[start:end])}],
            extra_body={"chat_template_kwargs": {"template": template_json}},
        )
        window_results.append(parse_response(response.choices[0].message.content, fields))

    return _merge_window_results(window_results)
