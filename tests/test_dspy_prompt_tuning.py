import pytest
from dspy.utils import DummyLM

from app.fields_import import import_fields
from app.models import ExtractionResult, Field, FieldExample
from scripts.dspy_prompt_tuning import (
    FailureExample,
    FieldCandidate,
    FieldResult,
    FieldScore,
    build_dspy_lm,
    build_markdown_loader,
    optimize_field,
    propose_candidates,
    run,
    score_field_candidate,
    write_results_csv,
)


class _FakeNerExtractor:
    def __init__(self, results_by_source: dict[str, list[ExtractionResult]]):
        self.results_by_source = results_by_source
        self.calls: list[dict] = []

    def extract(self, text, fields, *, source_filename=None):
        self.calls.append({"text": text, "fields": fields, "source_filename": source_filename})
        return self.results_by_source.get(source_filename, [])


class _FakePdfExtractor:
    def __init__(self, text: str):
        self.text = text
        self.call_count = 0

    def extract_text(self, pdf_bytes: bytes) -> str:
        self.call_count += 1
        return self.text


def _fields() -> list[Field]:
    return [
        Field(
            id=1,
            key="numero_devis",
            title="Numéro de devis",
            definition="définition actuelle du numéro",
            type="text",
        ),
        Field(
            id=2,
            key="nom_societe",
            title="Nom de la société",
            definition="définition actuelle de la société",
            type="text",
        ),
    ]


# --- score_field_candidate ---------------------------------------------------


def test_score_field_candidate_computes_tp_fp_fn():
    gold_documents = [
        {
            "source_file": "a.pdf",
            "annotations": {"numero_devis": {"value": "DEV-1", "evidence": {"page": 1}}},
        },
        {
            "source_file": "b.pdf",
            "annotations": {"numero_devis": {"value": "DEV-2", "evidence": {"page": 1}}},
        },
        {
            "source_file": "c.pdf",
            "annotations": {"numero_devis": {"value": None, "evidence": {"page": None}}},
        },
    ]
    results_by_source = {
        "a.pdf": [
            ExtractionResult(
                field_title="Numéro candidat", value="DEV-1", typed_value="DEV-1", page_number=1
            )
        ],
        "b.pdf": [
            ExtractionResult(
                field_title="Numéro candidat", value="WRONG", typed_value="WRONG", page_number=1
            )
        ],
        "c.pdf": [],
    }
    extractor = _FakeNerExtractor(results_by_source)

    score = score_field_candidate(
        "numero_devis",
        "Numéro candidat",
        "nouvelle définition",
        all_fields=_fields(),
        gold_documents=gold_documents,
        ner_extractor=extractor,
        markdown_loader=lambda source_file: f"markdown::{source_file}",
    )

    # a : match -> TP ; b : mauvaise valeur -> FP + FN ; c : gold vide, rien
    # extrait -> TN (exclu du calcul precision/recall)
    assert (score.tp, score.fp, score.fn) == (1, 1, 1)
    assert score.precision == 0.5
    assert score.recall == 0.5
    assert score.f1 == pytest.approx(0.5)
    assert score.failures == [
        FailureExample(source_file="b.pdf", gold_value="DEV-2", extracted_value="WRONG")
    ]


def test_score_field_candidate_leaves_other_fields_unchanged():
    gold_documents = [
        {
            "source_file": "a.pdf",
            "annotations": {"numero_devis": {"value": "DEV-1", "evidence": {"page": 1}}},
        },
    ]
    extractor = _FakeNerExtractor(
        {
            "a.pdf": [
                ExtractionResult(field_title="Titre candidat", value="DEV-1", typed_value="DEV-1")
            ]
        }
    )

    score_field_candidate(
        "numero_devis",
        "Titre candidat",
        "définition candidate",
        all_fields=_fields(),
        gold_documents=gold_documents,
        ner_extractor=extractor,
        markdown_loader=lambda source_file: "markdown",
    )

    assert len(extractor.calls) == 1
    fields_sent = {f.key: f for f in extractor.calls[0]["fields"]}
    assert fields_sent["numero_devis"].title == "Titre candidat"
    assert fields_sent["numero_devis"].definition == "définition candidate"
    assert fields_sent["nom_societe"].title == "Nom de la société"
    assert fields_sent["nom_societe"].definition == "définition actuelle de la société"


def test_score_field_candidate_skips_documents_without_the_field_annotated():
    gold_documents = [
        {"source_file": "a.pdf", "annotations": {"nom_societe": {"value": "ADALTRA"}}},
    ]
    extractor = _FakeNerExtractor({})

    score = score_field_candidate(
        "numero_devis",
        "Titre candidat",
        "définition candidate",
        all_fields=_fields(),
        gold_documents=gold_documents,
        ner_extractor=extractor,
        markdown_loader=lambda source_file: "markdown",
    )

    assert extractor.calls == []
    assert (score.tp, score.fp, score.fn) == (0, 0, 0)
    assert score.f1 == 0.0


# --- build_markdown_loader ----------------------------------------------------


# --- build_dspy_lm ------------------------------------------------------------


def test_build_dspy_lm_routes_openai_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    lm = build_dspy_lm("gpt-5-mini")

    assert lm.model == "openai/gpt-5-mini"
    assert lm.kwargs.get("api_key") == "sk-test"


def test_build_dspy_lm_routes_gemini_by_default(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "gemini-test-key")

    lm = build_dspy_lm("gemini-2.5-flash")

    assert lm.model == "gemini/gemini-2.5-flash"
    assert lm.kwargs.get("api_key") == "gemini-test-key"


def test_build_dspy_lm_requires_a_model_id():
    with pytest.raises(ValueError):
        build_dspy_lm(None)


# --- propose_candidates -------------------------------------------------------


def _numero_devis_field() -> Field:
    return Field(
        id=1,
        key="numero_devis",
        title="Numéro de devis",
        definition="définition actuelle du numéro",
        type="text",
    )


def test_propose_candidates_returns_n_candidates_from_a_dummy_lm():
    lm = DummyLM(
        [
            {"new_title": "Titre A", "new_definition": "Def A"},
            {"new_title": "Titre B", "new_definition": "Def B"},
            {"new_title": "Titre C", "new_definition": "Def C"},
        ]
    )

    candidates = propose_candidates(_numero_devis_field(), failures=[], n=3, lm=lm)

    assert len(candidates) == 3
    assert [c.title for c in candidates] == ["Titre A", "Titre B", "Titre C"]
    assert all(c.definition for c in candidates)


def test_propose_candidates_prompt_includes_current_field_state():
    lm = DummyLM([{"new_title": "Titre A", "new_definition": "Def A"}])

    propose_candidates(_numero_devis_field(), failures=[], n=1, lm=lm)

    prompt_content = lm.history[0]["messages"][1]["content"]
    assert "Numéro de devis" in prompt_content
    assert "définition actuelle du numéro" in prompt_content
    assert "text" in prompt_content


def test_propose_candidates_prompt_includes_failure_summary():
    lm = DummyLM([{"new_title": "Titre A", "new_definition": "Def A"}])
    failures = [
        FailureExample(source_file="a.pdf", gold_value="DEV-1", extracted_value="WRONG"),
    ]

    propose_candidates(_numero_devis_field(), failures=failures, n=1, lm=lm)

    prompt_content = lm.history[0]["messages"][1]["content"]
    assert "a.pdf" in prompt_content
    assert "DEV-1" in prompt_content
    assert "WRONG" in prompt_content


# --- optimize_field -------------------------------------------------------


def _score(f1: float, failures: list[FailureExample] | None = None) -> FieldScore:
    return FieldScore(f1=f1, precision=None, recall=None, tp=0, fp=0, fn=0, failures=failures or [])


def test_optimize_field_adopts_a_strictly_better_candidate():
    scores_by_key = {
        ("Numéro de devis", "définition actuelle du numéro"): _score(0.5),
        ("Meilleur titre", "meilleure définition"): _score(0.8),
    }

    def fake_score_fn(field_key, title, definition, **kwargs):
        return scores_by_key[(title, definition)]

    def fake_propose_fn(field, *, failures, n, lm):
        return [FieldCandidate(title="Meilleur titre", definition="meilleure définition")]

    result = optimize_field(
        "numero_devis",
        all_fields=[_numero_devis_field()],
        gold_documents=[],
        n_candidates=1,
        n_rounds=1,
        ner_extractor=None,
        markdown_loader=lambda source_file: "",
        lm=None,
        score_fn=fake_score_fn,
        propose_fn=fake_propose_fn,
    )

    assert result.best_title == "Meilleur titre"
    assert result.best_definition == "meilleure définition"
    assert result.best_f1 == 0.8
    assert result.baseline_f1 == 0.5
    assert result.best_label == "meilleur_titre"


def test_optimize_field_keeps_baseline_when_no_candidate_is_better():
    scores_by_key = {
        ("Numéro de devis", "définition actuelle du numéro"): _score(0.5),
        ("Pire titre", "pire définition"): _score(0.2),
    }

    def fake_score_fn(field_key, title, definition, **kwargs):
        return scores_by_key[(title, definition)]

    def fake_propose_fn(field, *, failures, n, lm):
        return [FieldCandidate(title="Pire titre", definition="pire définition")]

    result = optimize_field(
        "numero_devis",
        all_fields=[_numero_devis_field()],
        gold_documents=[],
        n_candidates=1,
        n_rounds=1,
        ner_extractor=None,
        markdown_loader=lambda source_file: "",
        lm=None,
        score_fn=fake_score_fn,
        propose_fn=fake_propose_fn,
    )

    assert result.best_title == "Numéro de devis"
    assert result.best_definition == "définition actuelle du numéro"
    assert result.best_f1 == 0.5
    assert result.best_label == "numero_devis"


def test_build_markdown_loader_reads_pdf_and_caches(tmp_path):
    data_test_dir = tmp_path / "data_test"
    data_test_dir.mkdir()
    (data_test_dir / "devis.pdf").write_bytes(b"fake-pdf-bytes")
    cache_dir = tmp_path / "cache"
    pdf_extractor = _FakePdfExtractor("# markdown extrait")

    load = build_markdown_loader(
        data_test_dir=data_test_dir, pdf_extractor=pdf_extractor, cache_dir=cache_dir
    )

    assert load("devis.pdf") == "# markdown extrait"
    assert load("devis.pdf") == "# markdown extrait"
    assert pdf_extractor.call_count == 1


# --- write_results_csv / run --------------------------------------------------


def _two_fields() -> list[Field]:
    return [
        Field(
            id=1,
            key="numero_devis",
            title="Numéro de devis",
            definition="définition actuelle du numéro",
            type="text",
            section="devis_contrat",
            examples=[FieldExample(context="DEV-1234", value=None, source="test")],
        ),
        Field(
            id=2,
            key="pourcentage_acompte",
            title="Pourcentage d'acompte",
            definition="définition actuelle du pourcentage",
            type="int",
            section="devis_contrat",
        ),
    ]


def test_write_results_csv_is_reparsable_by_import_fields(tmp_path):
    fields = _two_fields()
    results_by_key = {
        "numero_devis": FieldResult(
            field_key="numero_devis",
            baseline_title="Numéro de devis",
            baseline_definition="définition actuelle du numéro",
            baseline_f1=0.5,
            best_title="Numéro du devis",
            best_definition="nouvelle définition du numéro",
            best_label="numero_du_devis",
            best_f1=0.8,
        )
    }
    output_path = tmp_path / "results.csv"

    write_results_csv(fields, results_by_key, output_path)

    result = import_fields(output_path.read_bytes(), output_path.name)
    assert result.errors == []
    imported_by_key = {f.key: f for f in result.fields}
    assert imported_by_key["numero_du_devis"].title == "Numéro du devis"
    assert imported_by_key["numero_du_devis"].definition == "nouvelle définition du numéro"
    # champ non optimisé recopié tel quel (même clé, même title/definition)
    assert imported_by_key["pourcentage_acompte"].title == "Pourcentage d'acompte"
    assert imported_by_key["pourcentage_acompte"].type == "int"


def test_run_only_optimizes_requested_field_keys(tmp_path):
    fields = _two_fields()
    calls = []

    def fake_optimize_fn(field_key, **kwargs):
        calls.append(field_key)
        field = next(f for f in fields if f.key == field_key)
        return FieldResult(
            field_key=field_key,
            baseline_title=field.title,
            baseline_definition=field.definition,
            baseline_f1=0.5,
            best_title="Titre optimisé",
            best_definition="définition optimisée",
            best_label="titre_optimise",
            best_f1=0.9,
        )

    output_path = tmp_path / "results.csv"
    run(
        ["numero_devis"],
        all_fields=fields,
        gold_documents=[],
        n_candidates=1,
        n_rounds=1,
        output_path=output_path,
        optimize_fn=fake_optimize_fn,
    )

    assert calls == ["numero_devis"]
    result = import_fields(output_path.read_bytes(), output_path.name)
    imported_by_key = {f.key: f for f in result.fields}
    assert imported_by_key["titre_optimise"].title == "Titre optimisé"
    # pourcentage_acompte n'a pas été demandé -> inchangé
    assert imported_by_key["pourcentage_acompte"].title == "Pourcentage d'acompte"


def test_run_prints_baseline_and_best_f1(tmp_path, capsys):
    def fake_optimize_fn(field_key, **kwargs):
        return FieldResult(
            field_key=field_key,
            baseline_title="Numéro de devis",
            baseline_definition="def",
            baseline_f1=0.5,
            best_title="Numéro de devis",
            best_definition="def",
            best_label="numero_devis",
            best_f1=0.8,
        )

    run(
        ["numero_devis"],
        all_fields=_two_fields(),
        gold_documents=[],
        n_candidates=1,
        n_rounds=1,
        output_path=tmp_path / "results.csv",
        optimize_fn=fake_optimize_fn,
    )

    captured = capsys.readouterr()
    assert "numero_devis" in captured.out
    assert "0.500" in captured.out
    assert "0.800" in captured.out
