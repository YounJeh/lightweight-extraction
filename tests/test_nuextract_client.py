import json

import httpx
import openai
import pymupdf

from app.models import Field
from scripts.nuextract_client import (
    _MAX_RETRIES,
    _WINDOW_OVERLAP_PAGES,
    _WINDOW_SIZE_PAGES,
    _create_completion_with_retries,
    _merge_window_results,
    _page_windows,
    build_template,
    extract,
    parse_response,
    render_pdf_pages,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _field(key: str, type_: str = "text") -> Field:
    return Field(id=1, key=key, title=f"Titre {key}", definition="def", type=type_)


def _build_pdf(*page_texts: str) -> bytes:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_render_pdf_pages_returns_one_png_per_page_in_order():
    pdf_bytes = _build_pdf("page un", "page deux", "page trois")

    images = render_pdf_pages(pdf_bytes)

    assert len(images) == 3
    assert all(image.startswith(_PNG_MAGIC) for image in images)


def test_render_pdf_pages_on_a_single_page_document():
    pdf_bytes = _build_pdf("seule page")

    images = render_pdf_pages(pdf_bytes)

    assert len(images) == 1
    assert images[0].startswith(_PNG_MAGIC)


def test_page_windows_returns_a_single_window_for_a_short_document():
    assert _page_windows(2) == [(0, 2)]
    # == taille de fenêtre configurée, pas de découpage
    assert _page_windows(_WINDOW_SIZE_PAGES) == [(0, _WINDOW_SIZE_PAGES)]


def test_page_windows_splits_a_long_document_with_overlap():
    # Dérivé de la config réelle plutôt que des bornes en dur, pour rester
    # correct si _WINDOW_SIZE_PAGES/_WINDOW_OVERLAP_PAGES sont retouchées
    # (voir choix_techniques.md -- déjà ajusté une fois en réel, 5 -> 4).
    step = _WINDOW_SIZE_PAGES - _WINDOW_OVERLAP_PAGES
    page_count = _WINDOW_SIZE_PAGES * 3  # garantit plusieurs fenêtres

    windows = _page_windows(page_count)

    assert windows[0] == (0, _WINDOW_SIZE_PAGES)
    assert windows[1] == (step, step + _WINDOW_SIZE_PAGES)
    assert windows[-1][1] == page_count
    assert len(windows) > 1


def test_page_windows_covers_every_page_exactly_once_at_the_boundaries():
    windows = _page_windows(25)

    covered = set()
    for start, end in windows:
        covered.update(range(start, end))
    assert covered == set(range(25))
    assert windows[-1][1] == 25  # la dernière fenêtre atteint bien la fin


def _extraction(field_title: str, value: str) -> "ExtractionResult":
    from app.models import ExtractionResult

    return ExtractionResult(
        field_title=field_title, value=value, source="nuextract", typed_value=value or None
    )


def test_merge_window_results_keeps_the_first_non_empty_value():
    window1 = [_extraction("Numéro de devis", "")]
    window2 = [_extraction("Numéro de devis", "n°6952")]
    window3 = [_extraction("Numéro de devis", "AUTRE")]

    merged = _merge_window_results([window1, window2, window3])

    assert [r.value for r in merged] == ["n°6952"]


def test_merge_window_results_stays_empty_when_no_window_finds_a_value():
    merged = _merge_window_results(
        [[_extraction("Numéro de devis", "")], [_extraction("Numéro de devis", "")]]
    )

    assert merged[0].value == ""


def test_merge_window_results_preserves_field_order():
    window1 = [_extraction("A", ""), _extraction("B", "")]
    window2 = [_extraction("A", ""), _extraction("B", "valeur B")]

    merged = _merge_window_results([window1, window2])

    assert [r.field_title for r in merged] == ["A", "B"]


def test_build_template_maps_every_field_to_verbatim_string():
    fields = [_field("numero_devis"), _field("montant", "float")]

    template = build_template(fields)

    assert template == {"numero_devis": "verbatim-string", "montant": "verbatim-string"}


def test_parse_response_maps_present_fields_with_type_coercion():
    fields = [_field("numero_devis"), _field("pourcentage", "int")]
    content = json.dumps({"numero_devis": "n°6952", "pourcentage": "30"})

    results = parse_response(content, fields)

    by_title = {r.field_title: r for r in results}
    assert by_title["Titre numero_devis"].value == "n°6952"
    assert by_title["Titre numero_devis"].typed_value == "n°6952"
    assert by_title["Titre numero_devis"].source == "nuextract"
    assert by_title["Titre pourcentage"].typed_value == "30"
    assert by_title["Titre pourcentage"].type_error is None


def test_parse_response_flags_a_value_that_does_not_coerce_to_the_field_type():
    fields = [_field("pourcentage", "int")]
    content = json.dumps({"pourcentage": "trente"})

    results = parse_response(content, fields)

    assert results[0].type_error is not None


def test_parse_response_produces_an_empty_row_for_a_missing_or_blank_field():
    fields = [_field("numero_devis"), _field("nom_societe")]
    content = json.dumps({"numero_devis": "  ", "autre_champ": "valeur"})

    results = parse_response(content, fields)

    by_title = {r.field_title: r for r in results}
    assert by_title["Titre numero_devis"].value == ""
    assert by_title["Titre numero_devis"].typed_value is None
    assert by_title["Titre nom_societe"].value == ""


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


def _server_error_503() -> openai.InternalServerError:
    request = httpx.Request("POST", "http://test")
    return openai.InternalServerError(
        "no upstreams available", response=httpx.Response(503, request=request), body=None
    )


class _ScriptedCompletions:
    """Simule `client.chat.completions.create` : consomme `outcomes` dans
    l'ordre, un par appel -- une exception est levée, une chaîne est
    renvoyée comme contenu de réponse. Un seul type de faux client pour
    tous les scénarios de ce fichier (contenu fixe, séquence de fenêtres,
    échecs transitoires suivis d'un succès) : une séquence d'exceptions
    et/ou de contenus couvre chacun de ces cas."""

    def __init__(self, outcomes: list):
        self._outcomes = list(outcomes)
        self.received_kwargs_per_call: list[dict] = []

    def create(self, **kwargs):
        self.received_kwargs_per_call.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


class _ScriptedClient:
    def __init__(self, outcomes: list):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _ScriptedCompletions(outcomes)


def test_create_completion_with_retries_succeeds_after_transient_503s():
    fake_client = _ScriptedClient([_server_error_503(), _server_error_503(), "ok"])
    sleeps: list[float] = []

    result = _create_completion_with_retries(fake_client, sleep=sleeps.append)

    assert result.choices[0].message.content == "ok"
    assert len(fake_client.chat.completions.received_kwargs_per_call) == 3
    assert sleeps == [5.0, 10.0]  # backoff exponentiel : 5s puis 10s


def test_create_completion_with_retries_calls_on_retry_with_each_delay():
    fake_client = _ScriptedClient([_server_error_503(), _server_error_503(), "ok"])
    delays: list[float] = []

    _create_completion_with_retries(fake_client, sleep=lambda _: None, on_retry=delays.append)

    assert delays == [5.0, 10.0]


def test_create_completion_with_retries_raises_after_exhausting_attempts():
    fake_client = _ScriptedClient([_server_error_503() for _ in range(_MAX_RETRIES)])

    try:
        _create_completion_with_retries(fake_client, sleep=lambda _: None)
        assert False, "devrait lever après _MAX_RETRIES tentatives"
    except openai.InternalServerError:
        pass

    assert len(fake_client.chat.completions.received_kwargs_per_call) == _MAX_RETRIES


def test_create_completion_with_retries_tolerates_a_slow_cold_start():
    # Régression : "item 0" du gold (data_test/OFR2603012513 - ENTECH.pdf)
    # a épuisé un budget de 8 tentatives (~155s) en réel avant ce fix --
    # reproduit deux fois, cold-start plus lent qu'anticipé, pas un bug
    # propre au document. 10 échecs consécutifs auraient fait lever cette
    # fonction sous l'ancien _MAX_RETRIES=8 ; le budget élargi (20) les
    # tolère.
    fake_client = _ScriptedClient([_server_error_503() for _ in range(10)] + ["ok"])

    result = _create_completion_with_retries(fake_client, sleep=lambda _: None)

    assert result.choices[0].message.content == "ok"
    assert len(fake_client.chat.completions.received_kwargs_per_call) == 11


def test_extract_sends_one_image_per_page_and_the_verbatim_string_template():
    pdf_bytes = _build_pdf("page un", "page deux")
    fields = [_field("numero_devis")]
    fake_client = _ScriptedClient([json.dumps({"numero_devis": "n°6952"})])

    results = extract(pdf_bytes, fields, client=fake_client)

    kwargs = fake_client.chat.completions.received_kwargs_per_call[0]
    assert len(kwargs["messages"][0]["content"]) == 2  # une image par page
    template = json.loads(kwargs["extra_body"]["chat_template_kwargs"]["template"])
    assert template == {"numero_devis": "verbatim-string"}
    assert results[0].value == "n°6952"
    assert results[0].source == "nuextract"


def test_extract_windows_a_long_document_and_merges_across_calls():
    # Nombre de pages dérivé de la config réelle plutôt qu'en dur --
    # garantit exactement 2 fenêtres quels que soient
    # _WINDOW_SIZE_PAGES/_WINDOW_OVERLAP_PAGES (voir _page_windows).
    page_count = 2 * _WINDOW_SIZE_PAGES - _WINDOW_OVERLAP_PAGES
    expected_windows = _page_windows(page_count)
    assert len(expected_windows) == 2  # sinon la formule ci-dessus ne tient plus

    pdf_bytes = _build_pdf(*[f"page {i}" for i in range(page_count)])
    fields = [_field("numero_devis")]
    # 1ère fenêtre : rien trouvé. 2e fenêtre : trouvé (dans la zone
    # d'overlap avec la 1ère fenêtre).
    fake_client = _ScriptedClient(
        [json.dumps({"numero_devis": ""}), json.dumps({"numero_devis": "n°6952"})]
    )

    results = extract(pdf_bytes, fields, client=fake_client)

    calls = fake_client.chat.completions.received_kwargs_per_call
    assert len(calls) == 2  # deux appels, un par fenêtre
    for call, (start, end) in zip(calls, expected_windows):
        assert len(call["messages"][0]["content"]) == end - start
    assert results[0].value == "n°6952"  # trouvé en fenêtre 2, fusionné correctement


def test_extract_accumulates_on_retry_across_multiple_windows(monkeypatch):
    monkeypatch.setattr("scripts.nuextract_client.time.sleep", lambda _: None)
    pdf_bytes = _build_pdf(*[f"page {i}" for i in range(7)])  # -> 2 fenêtres
    fields = [_field("numero_devis")]
    fake_client = _ScriptedClient(
        [
            _server_error_503(),
            json.dumps({"numero_devis": ""}),  # fenêtre 1 : échoue puis réussit
            _server_error_503(),
            json.dumps({"numero_devis": "n°6952"}),  # fenêtre 2 : échoue puis réussit
        ]
    )
    delays: list[float] = []

    results = extract(pdf_bytes, fields, client=fake_client, on_retry=delays.append)

    assert delays == [5.0, 5.0]  # un retry par fenêtre, chacune repart de l'initial backoff
    assert results[0].value == "n°6952"


def test_extract_makes_a_single_call_for_a_short_document():
    pdf_bytes = _build_pdf(*[f"page {i}" for i in range(3)])
    fields = [_field("numero_devis")]
    fake_client = _ScriptedClient([json.dumps({"numero_devis": "n°6952"})])

    extract(pdf_bytes, fields, client=fake_client)

    assert len(fake_client.chat.completions.received_kwargs_per_call) == 1
