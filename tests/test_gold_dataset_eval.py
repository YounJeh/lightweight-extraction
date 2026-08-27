from types import SimpleNamespace

from app.models import Field
from scripts.gold_dataset_eval import (
    GOLD_FIELDS_CSV,
    build_field_evaluator,
    build_task,
    load_gold_fields,
)

_EXPECTED_KEYS = {
    "numero_devis",
    "nom_societe",
    "pourcentage_acompte",
    "pourcentage_solde",
    "delai_paiement_solde_jours",
    "duree_validite_offre",
}


def test_load_gold_fields_returns_the_six_gold_fields():
    fields = load_gold_fields()

    assert {f.key for f in fields} == _EXPECTED_KEYS
    assert all(f.id is not None for f in fields)


def test_load_gold_fields_types_match_the_gold_dataset():
    fields = {f.key: f for f in load_gold_fields()}

    assert fields["pourcentage_acompte"].type == "int"
    assert fields["pourcentage_solde"].type == "int"
    assert fields["numero_devis"].type == "text"


def test_load_gold_fields_never_touches_the_real_app_db(tmp_path, monkeypatch):
    # Sentinel : si load_gold_fields écrivait par erreur dans le cwd ou une
    # DB par défaut, ce test le détecterait en s'assurant qu'aucun fichier
    # n'apparaît dans un répertoire de travail vide dédié.
    monkeypatch.chdir(tmp_path)

    load_gold_fields()

    assert list(tmp_path.iterdir()) == []


def test_gold_fields_csv_fixture_exists():
    assert GOLD_FIELDS_CSV.exists()
    assert GOLD_FIELDS_CSV.name == "gold_devis_fields.csv"


class _FakePdfExtractor:
    def __init__(self, text: str):
        self.text = text
        self.received_pdf_bytes: bytes | None = None

    def extract_text(self, pdf_bytes: bytes) -> str:
        self.received_pdf_bytes = pdf_bytes
        return self.text


class _FakeNerExtractor:
    def __init__(self, results):
        self.results = results
        self.received: dict | None = None

    def extract(self, text, fields, *, source_filename=None):
        self.received = {
            "text": text,
            "fields": fields,
            "source_filename": source_filename,
        }
        return self.results


class _FakeExtractionResult:
    def __init__(self, field_title: str, value: str):
        self.field_title = field_title
        self.value = value

    def model_dump(self):
        return {"field_title": self.field_title, "value": self.value}


def _numero_devis_field() -> Field:
    return Field(
        id=1,
        key="numero_devis",
        title="Numéro de devis",
        definition="Numéro du devis",
        type="text",
    )


def test_build_task_reads_the_referenced_pdf_and_extracts_selected_fields(tmp_path):
    field = _numero_devis_field()
    (tmp_path / "devis.pdf").write_bytes(b"%PDF-fake-bytes")
    pdf_extractor = _FakePdfExtractor("texte extrait du PDF")
    ner_extractor = _FakeNerExtractor([_FakeExtractionResult("Numéro de devis", "42")])

    task = build_task(
        {"numero_devis": field},
        pdf_extractor=pdf_extractor,
        ner_extractor=ner_extractor,
        data_test_dir=tmp_path,
    )
    item = SimpleNamespace(
        input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]}
    )

    output = task(item=item)

    assert pdf_extractor.received_pdf_bytes == b"%PDF-fake-bytes"
    assert ner_extractor.received == {
        "text": "texte extrait du PDF",
        "fields": [field],
        "source_filename": "devis.pdf",
    }
    assert output == [{"field_title": "Numéro de devis", "value": "42"}]


def test_build_task_resolves_only_the_fields_listed_for_this_item(tmp_path):
    numero = _numero_devis_field()
    other = Field(id=2, key="nom_societe", title="Nom de la société", definition="d", type="text")
    (tmp_path / "devis.pdf").write_bytes(b"%PDF")
    pdf_extractor = _FakePdfExtractor("texte")
    ner_extractor = _FakeNerExtractor([])

    task = build_task(
        {"numero_devis": numero, "nom_societe": other},
        pdf_extractor=pdf_extractor,
        ner_extractor=ner_extractor,
        data_test_dir=tmp_path,
    )
    item = SimpleNamespace(
        input={"source_file": "devis.pdf", "field_keys": ["numero_devis"]}
    )

    task(item=item)

    assert ner_extractor.received["fields"] == [numero]


def _evaluations_by_name(evaluations):
    return {ev.name: ev for ev in evaluations}


def test_field_evaluator_marks_exact_match_true_when_all_fields_match():
    field = _numero_devis_field()
    evaluator = build_field_evaluator({"numero_devis": field})

    evaluations = evaluator(
        output=[{"field_title": "Numéro de devis", "typed_value": "n°6952", "page_number": 1}],
        expected_output={
            "numero_devis": {"value": "n°6952", "evidence": {"page": 1, "text": None}}
        },
        metadata={"human_validation": True, "document_id": 3},
    )

    by_name = _evaluations_by_name(evaluations)
    assert by_name["match:numero_devis"].value == "tp"
    assert by_name["match:numero_devis"].metadata == {"grounding_match": True}
    assert by_name["exact_match"].value is True
    assert by_name["human_validation"].value is True


def test_field_evaluator_marks_exact_match_false_on_a_wrong_value():
    field = _numero_devis_field()
    evaluator = build_field_evaluator({"numero_devis": field})

    evaluations = evaluator(
        output=[{"field_title": "Numéro de devis", "typed_value": "AUTRE", "page_number": 1}],
        expected_output={
            "numero_devis": {"value": "n°6952", "evidence": {"page": 1, "text": None}}
        },
        metadata={"human_validation": True},
    )

    by_name = _evaluations_by_name(evaluations)
    kinds = [ev.value for ev in evaluations if ev.name == "match:numero_devis"]
    assert set(kinds) == {"fp", "fn"}
    assert by_name["exact_match"].value is False


def test_field_evaluator_handles_a_field_with_no_extraction_at_all():
    field = _numero_devis_field()
    evaluator = build_field_evaluator({"numero_devis": field})

    evaluations = evaluator(
        output=[],
        expected_output={
            "numero_devis": {"value": "n°6952", "evidence": {"page": 1, "text": None}}
        },
        metadata={"human_validation": False},
    )

    by_name = _evaluations_by_name(evaluations)
    assert by_name["match:numero_devis"].value == "fn"
    assert by_name["exact_match"].value is False
    assert by_name["human_validation"].value is False


def test_field_evaluator_true_negative_does_not_break_exact_match():
    field = Field(
        id=2, key="pourcentage_solde", title="Pourcentage du solde", definition="d", type="int"
    )
    evaluator = build_field_evaluator({"pourcentage_solde": field})

    evaluations = evaluator(
        output=[],
        expected_output={
            "pourcentage_solde": {"value": None, "evidence": {"page": None, "text": None}}
        },
        metadata={"human_validation": True},
    )

    by_name = _evaluations_by_name(evaluations)
    assert by_name["match:pourcentage_solde"].value == "tn"
    assert by_name["exact_match"].value is True
