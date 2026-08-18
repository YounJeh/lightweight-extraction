from langextract import data

from app.models import Field
from app.tools import ner_langextract
from app.tools.ner_langextract import LangExtractNerExtractor


def _fields() -> list[Field]:
    return [
        Field(id=1, title="Condition de règlement", definition="...", examples=[]),
        Field(id=2, title="Avance forfaitaire", definition="...", examples=[]),
    ]


def _grounded(field_title: str, text_value: str, start_pos: int) -> "data.Extraction":
    return data.Extraction(
        extraction_class=field_title,
        extraction_text=text_value,
        char_interval=data.CharInterval(start_pos=start_pos, end_pos=start_pos + len(text_value)),
    )


def _ungrounded(field_title: str, text_value: str = "") -> "data.Extraction":
    return data.Extraction(
        extraction_class=field_title, extraction_text=text_value, char_interval=None
    )


def test_extract_drops_fields_with_zero_grounded_candidates(monkeypatch):
    text = "Aucune information pertinente ici."
    annotated = data.AnnotatedDocument(
        extractions=[
            _ungrounded("Avance forfaitaire", ""),
            _ungrounded("Avance forfaitaire", ">>Aucune valeur présente pour Avance forfaitaire<<"),
        ],
        text=text,
    )
    calls = []
    monkeypatch.setattr(
        ner_langextract.langextract,
        "extract",
        lambda **kw: (calls.append(kw), annotated)[1],
    )

    results = LangExtractNerExtractor().extract(text, _fields())

    assert results == []
    assert len(calls) == 1  # pas d'arbitrage déclenché


def test_extract_accepts_single_grounded_candidate_without_arbitration(monkeypatch):
    text = "Paiement à 30 jours après réception."
    candidate = _grounded("Avance forfaitaire", "30 jours", text.index("30 jours"))
    annotated = data.AnnotatedDocument(extractions=[candidate], text=text)
    calls = []
    monkeypatch.setattr(
        ner_langextract.langextract,
        "extract",
        lambda **kw: (calls.append(kw), annotated)[1],
    )

    results = LangExtractNerExtractor().extract(text, _fields())

    assert len(results) == 1
    assert results[0].field_title == "Avance forfaitaire"
    assert results[0].value == "30 jours"
    assert len(calls) == 1  # pas d'arbitrage déclenché


def test_extract_merges_same_normalized_value_without_arbitration(monkeypatch):
    text = "30 JOURS puis encore 30 jours plus loin dans le texte."
    first = _grounded("Avance forfaitaire", "30 JOURS", text.index("30 JOURS"))
    second = _grounded("Avance forfaitaire", "30 jours", text.rindex("30 jours"))
    annotated = data.AnnotatedDocument(extractions=[first, second], text=text)
    calls = []
    monkeypatch.setattr(
        ner_langextract.langextract,
        "extract",
        lambda **kw: (calls.append(kw), annotated)[1],
    )

    results = LangExtractNerExtractor().extract(text, _fields())

    assert len(results) == 1
    assert results[0].value == "30 JOURS"  # première occurrence
    assert len(calls) == 1  # même valeur normalisée -> pas d'arbitrage


def test_extract_arbitrates_genuine_conflict_via_second_llm_call(monkeypatch):
    text = (
        "Par chèque ou virement à 30 jours après réception. "
        "15% à l'avancement sur situations mensuelles."
    )
    first = _grounded(
        "Condition de règlement",
        "Par chèque ou virement à 30 jours.",
        text.index("Par chèque"),
    )
    second = _grounded(
        "Condition de règlement",
        "15% à l'avancement sur situations mensuelles.",
        text.index("15%"),
    )
    main_annotated = data.AnnotatedDocument(extractions=[first, second], text=text)
    arbitration_annotated = data.AnnotatedDocument(
        extractions=[
            data.Extraction(
                extraction_class="selection",
                extraction_text="15% à l'avancement sur situations mensuelles.",
            )
        ],
        text="arbitration input",
    )

    calls = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return main_annotated
        return arbitration_annotated

    monkeypatch.setattr(ner_langextract.langextract, "extract", fake_extract)

    results = LangExtractNerExtractor().extract(text, _fields())

    assert len(results) == 1
    assert results[0].value == "15% à l'avancement sur situations mensuelles."
    assert len(calls) == 2  # extraction principale + arbitrage
    assert "Condition de règlement" in calls[1]["prompt_description"]


def test_extract_sets_value_type_and_no_error_for_valid_typed_value(monkeypatch):
    text = "Âge : 30 ans."
    candidate = data.Extraction(
        extraction_class="Âge",
        extraction_text="30 ans",
        char_interval=data.CharInterval(
            start_pos=text.index("30 ans"), end_pos=text.index("30 ans") + len("30 ans")
        ),
        attributes={"value": "30"},
    )
    annotated = data.AnnotatedDocument(extractions=[candidate], text=text)
    monkeypatch.setattr(ner_langextract.langextract, "extract", lambda **kw: annotated)
    fields = [Field(id=1, title="Âge", definition="Âge de la personne", type="int")]

    results = LangExtractNerExtractor().extract(text, fields)

    assert len(results) == 1
    assert results[0].value == "30 ans"  # grounding textuel inchangé
    assert results[0].typed_value == "30"  # valeur typée exposée séparément
    assert results[0].value_type == "int"
    assert results[0].type_error is None


def test_extract_sets_type_error_when_value_not_convertible(monkeypatch):
    text = "Âge : inconnu."
    candidate = data.Extraction(
        extraction_class="Âge",
        extraction_text="inconnu",
        char_interval=data.CharInterval(
            start_pos=text.index("inconnu"), end_pos=text.index("inconnu") + len("inconnu")
        ),
    )
    annotated = data.AnnotatedDocument(extractions=[candidate], text=text)
    monkeypatch.setattr(ner_langextract.langextract, "extract", lambda **kw: annotated)
    fields = [Field(id=1, title="Âge", definition="Âge de la personne", type="int")]

    results = LangExtractNerExtractor().extract(text, fields)

    assert len(results) == 1
    assert results[0].value == "inconnu"  # le grounding reste malgré l'erreur
    assert results[0].typed_value == "inconnu"
    assert results[0].value_type == "int"
    assert results[0].type_error is not None


def test_extract_falls_back_to_extraction_text_when_attributes_missing(monkeypatch):
    text = "Âge : 42."
    candidate = data.Extraction(
        extraction_class="Âge",
        extraction_text="42",
        char_interval=data.CharInterval(
            start_pos=text.index("42"), end_pos=text.index("42") + len("42")
        ),
        attributes=None,
    )
    annotated = data.AnnotatedDocument(extractions=[candidate], text=text)
    monkeypatch.setattr(ner_langextract.langextract, "extract", lambda **kw: annotated)
    fields = [Field(id=1, title="Âge", definition="Âge de la personne", type="int")]

    results = LangExtractNerExtractor().extract(text, fields)

    assert results[0].type_error is None


def test_extract_falls_back_to_first_occurrence_when_arbitration_is_unparseable(monkeypatch):
    text = "Valeur A ici. Valeur B là."
    first = _grounded("Avance forfaitaire", "Valeur A", text.index("Valeur A"))
    second = _grounded("Avance forfaitaire", "Valeur B", text.index("Valeur B"))
    main_annotated = data.AnnotatedDocument(extractions=[first, second], text=text)
    # Arbitrage renvoie un texte qui ne correspond à aucun candidat
    arbitration_annotated = data.AnnotatedDocument(
        extractions=[
            data.Extraction(extraction_class="selection", extraction_text="Valeur C inconnue")
        ],
        text="arbitration input",
    )

    calls = []

    def fake_extract(**kwargs):
        calls.append(kwargs)
        return main_annotated if len(calls) == 1 else arbitration_annotated

    monkeypatch.setattr(ner_langextract.langextract, "extract", fake_extract)

    results = LangExtractNerExtractor().extract(text, _fields())

    assert len(results) == 1
    assert results[0].value == "Valeur A"  # repli sur la première occurrence
