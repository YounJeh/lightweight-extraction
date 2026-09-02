import json

import httpx
import openai
import pymupdf

from app.models import Field
from scripts.nuextract_client import (
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
    assert _page_windows(3) == [(0, 3)]
    assert _page_windows(5) == [(0, 5)]  # == taille de fenêtre, pas de découpage


def test_page_windows_splits_a_long_document_with_overlap():
    windows = _page_windows(12)

    assert windows == [(0, 5), (4, 9), (8, 12)]


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


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content
        self.received_kwargs: dict | None = None

    def create(self, **kwargs):
        self.received_kwargs = kwargs
        return _FakeResponse(self._content)


class _FakeClient:
    def __init__(self, content: str):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _FakeCompletions(content)


def _server_error_503() -> openai.InternalServerError:
    request = httpx.Request("POST", "http://test")
    return openai.InternalServerError(
        "no upstreams available", response=httpx.Response(503, request=request), body=None
    )


class _FlakyCompletions:
    """Simule `client.chat.completions.create` : lève chaque exception de
    `side_effects` dans l'ordre, puis renvoie `result` au premier appel
    restant."""

    def __init__(self, side_effects: list[Exception], result):
        self._side_effects = list(side_effects)
        self._result = result
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        if self._side_effects:
            raise self._side_effects.pop(0)
        return self._result


def test_create_completion_with_retries_succeeds_after_transient_503s():
    completions = _FlakyCompletions([_server_error_503(), _server_error_503()], "ok")
    fake_client = type("_C", (), {"chat": type("_Chat", (), {"completions": completions})()})()
    sleeps: list[float] = []

    result = _create_completion_with_retries(fake_client, sleep=sleeps.append)

    assert result == "ok"
    assert completions.call_count == 3
    assert sleeps == [5.0, 10.0]  # backoff exponentiel : 5s puis 10s


def test_create_completion_with_retries_calls_on_retry_with_each_delay():
    completions = _FlakyCompletions([_server_error_503(), _server_error_503()], "ok")
    fake_client = type("_C", (), {"chat": type("_Chat", (), {"completions": completions})()})()
    delays: list[float] = []

    _create_completion_with_retries(fake_client, sleep=lambda _: None, on_retry=delays.append)

    assert delays == [5.0, 10.0]


def test_create_completion_with_retries_raises_after_exhausting_attempts():
    completions = _FlakyCompletions([_server_error_503() for _ in range(8)], "unreachable")
    fake_client = type("_C", (), {"chat": type("_Chat", (), {"completions": completions})()})()

    try:
        _create_completion_with_retries(fake_client, sleep=lambda _: None)
        assert False, "devrait lever après _MAX_RETRIES tentatives"
    except openai.InternalServerError:
        pass

    assert completions.call_count == 8  # _MAX_RETRIES, aucune tentative en plus


def test_extract_sends_one_image_per_page_and_the_verbatim_string_template():
    pdf_bytes = _build_pdf("page un", "page deux")
    fields = [_field("numero_devis")]
    fake_client = _FakeClient(json.dumps({"numero_devis": "n°6952"}))

    results = extract(pdf_bytes, fields, client=fake_client)

    kwargs = fake_client.chat.completions.received_kwargs
    assert len(kwargs["messages"][0]["content"]) == 2  # une image par page
    template = json.loads(kwargs["extra_body"]["chat_template_kwargs"]["template"])
    assert template == {"numero_devis": "verbatim-string"}
    assert results[0].value == "n°6952"
    assert results[0].source == "nuextract"


class _FakeCompletionsSequence:
    """Comme `_FakeCompletions`, mais renvoie un contenu différent à
    chaque appel (dans l'ordre) — simule plusieurs fenêtres d'un même
    document, chacune avec sa propre réponse."""

    def __init__(self, contents: list[str]):
        self._contents = list(contents)
        self.received_kwargs_per_call: list[dict] = []

    def create(self, **kwargs):
        self.received_kwargs_per_call.append(kwargs)
        return _FakeResponse(self._contents[len(self.received_kwargs_per_call) - 1])


class _FakeClientSequence:
    def __init__(self, contents: list[str]):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _FakeCompletionsSequence(contents)


def test_extract_windows_a_long_document_and_merges_across_calls():
    # 7 pages -> 2 fenêtres (0,5) et (4,7), voir _page_windows.
    pdf_bytes = _build_pdf(*[f"page {i}" for i in range(7)])
    fields = [_field("numero_devis")]
    # 1ère fenêtre : rien trouvé. 2e fenêtre : trouvé (page 4-6, avec
    # overlap sur la page 4 de la 1ère fenêtre).
    fake_client = _FakeClientSequence(
        [json.dumps({"numero_devis": ""}), json.dumps({"numero_devis": "n°6952"})]
    )

    results = extract(pdf_bytes, fields, client=fake_client)

    calls = fake_client.chat.completions.received_kwargs_per_call
    assert len(calls) == 2  # deux appels, un par fenêtre
    assert len(calls[0]["messages"][0]["content"]) == 5  # fenêtre 1 : pages 0-4
    assert len(calls[1]["messages"][0]["content"]) == 3  # fenêtre 2 : pages 4-6
    assert results[0].value == "n°6952"  # trouvé en fenêtre 2, fusionné correctement


class _ScriptedCompletions:
    """Consomme `outcomes` dans l'ordre : une exception est levée, une
    chaîne est renvoyée comme contenu de réponse -- simule une séquence
    échec/succès arbitraire à travers plusieurs fenêtres."""

    def __init__(self, outcomes: list):
        self._outcomes = list(outcomes)

    def create(self, **kwargs):
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)


class _ScriptedClient:
    def __init__(self, outcomes: list):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _ScriptedCompletions(outcomes)


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
    fake_client = _FakeClientSequence([json.dumps({"numero_devis": "n°6952"})])

    extract(pdf_bytes, fields, client=fake_client)

    assert len(fake_client.chat.completions.received_kwargs_per_call) == 1
