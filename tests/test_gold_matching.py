import pytest

from scripts.gold_matching import classify_field, precision_recall_f1, values_match

# --- values_match : cas nominaux par type ---------------------------------


def test_text_match_ignores_case_and_extra_whitespace():
    assert values_match("SAS  Adiwatt", "sas adiwatt", "text") is True


def test_text_no_match_different_content():
    assert values_match("SAS Adiwatt", "SCBM", "text") is False


def test_numeric_match_tolerates_percent_suffix():
    assert values_match(30, "30 %", "int") is True


def test_numeric_match_tolerates_comma_decimal():
    assert values_match(2.5, "2,5", "float") is True


def test_numeric_no_match_different_value():
    assert values_match(30, "70", "int") is False


def test_date_match_after_normalization():
    assert values_match("2026-04-21", "le 2026-04-21 à Paris", "date") is True


def test_date_no_match_different_day():
    assert values_match("2026-04-21", "2026-04-22", "date") is False


def test_bool_match_across_token_families():
    assert values_match("oui", "true", "bool") is True
    assert values_match("non", "false", "bool") is True


def test_bool_no_match_opposite_values():
    assert values_match("oui", "non", "bool") is False


# --- classify_field : TP/FP/FN/TN ------------------------------------------


def test_classify_field_true_positive_on_match():
    outcomes = classify_field(
        field_key="numero_devis",
        field_type="text",
        gold_value="n°6952",
        gold_page=1,
        extracted_value="n°6952",
        extracted_page=1,
    )
    assert len(outcomes) == 1
    assert outcomes[0].kind == "tp"
    assert outcomes[0].grounding_match is True


def test_classify_field_true_positive_with_wrong_page_is_grounding_mismatch():
    outcomes = classify_field(
        field_key="numero_devis",
        field_type="text",
        gold_value="n°6952",
        gold_page=1,
        extracted_value="n°6952",
        extracted_page=3,
    )
    assert outcomes[0].kind == "tp"
    assert outcomes[0].grounding_match is False


def test_classify_field_true_positive_without_gold_page_has_no_grounding_signal():
    outcomes = classify_field(
        field_key="numero_devis",
        field_type="text",
        gold_value="n°6952",
        gold_page=None,
        extracted_value="n°6952",
        extracted_page=1,
    )
    assert outcomes[0].kind == "tp"
    assert outcomes[0].grounding_match is None


def test_classify_field_true_negative_when_both_absent():
    outcomes = classify_field(
        field_key="pourcentage_acompte",
        field_type="int",
        gold_value=None,
        gold_page=None,
        extracted_value=None,
        extracted_page=None,
    )
    assert [o.kind for o in outcomes] == ["tn"]


def test_classify_field_false_positive_when_gold_absent_but_extracted_present():
    outcomes = classify_field(
        field_key="pourcentage_acompte",
        field_type="int",
        gold_value=None,
        gold_page=None,
        extracted_value="30",
        extracted_page=2,
    )
    assert [o.kind for o in outcomes] == ["fp"]


def test_classify_field_false_negative_when_gold_present_but_nothing_extracted():
    outcomes = classify_field(
        field_key="pourcentage_acompte",
        field_type="int",
        gold_value=30,
        gold_page=2,
        extracted_value=None,
        extracted_page=None,
    )
    assert [o.kind for o in outcomes] == ["fn"]


def test_classify_field_wrong_value_counts_as_both_fp_and_fn():
    outcomes = classify_field(
        field_key="pourcentage_acompte",
        field_type="int",
        gold_value=30,
        gold_page=2,
        extracted_value="70",
        extracted_page=2,
    )
    assert {o.kind for o in outcomes} == {"fp", "fn"}
    assert len(outcomes) == 2


# --- precision_recall_f1 ---------------------------------------------------


def test_precision_recall_f1_all_zero_counts_is_none():
    assert precision_recall_f1(0, 0, 0) == (None, None, None)


def test_precision_recall_f1_perfect_score():
    assert precision_recall_f1(5, 0, 0) == (1.0, 1.0, 1.0)


def test_precision_recall_f1_computes_expected_values():
    precision, recall, f1 = precision_recall_f1(tp=3, fp=1, fn=2)
    assert precision == 0.75
    assert recall == 0.6
    assert f1 == pytest.approx(0.6667, abs=1e-4)


def test_precision_recall_f1_no_predicted_positives_precision_is_none():
    precision, recall, f1 = precision_recall_f1(tp=0, fp=0, fn=3)
    assert precision is None
    assert recall == 0.0
    assert f1 is None
