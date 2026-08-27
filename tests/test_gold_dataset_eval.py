from scripts.gold_dataset_eval import GOLD_FIELDS_CSV, load_gold_fields

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
