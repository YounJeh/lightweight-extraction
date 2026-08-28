from scripts.text_slug import slugify_title

# --- Régression contre les labels existants (tests/data/gold_devis_fields.csv) --


def test_slugify_title_matches_existing_label_numero_devis():
    assert slugify_title("Numéro de devis") == "numero_devis"


def test_slugify_title_matches_existing_label_nom_societe():
    assert slugify_title("Nom de la société") == "nom_societe"


def test_slugify_title_matches_existing_label_pourcentage_acompte():
    assert slugify_title("Pourcentage d’acompte") == "pourcentage_acompte"


def test_slugify_title_matches_existing_label_pourcentage_solde():
    assert slugify_title("Pourcentage du solde") == "pourcentage_solde"


def test_slugify_title_matches_existing_label_duree_validite_offre():
    assert slugify_title("Durée de validité de l'offre") == "duree_validite_offre"


# --- Cas génériques ---------------------------------------------------------


def test_slugify_title_collapses_repeated_punctuation_and_spaces():
    assert slugify_title("Délai  de paiement !!") == "delai_paiement"


def test_slugify_title_has_no_leading_or_trailing_underscore():
    slug = slugify_title("  Référence client  ")
    assert not slug.startswith("_")
    assert not slug.endswith("_")
    assert slug == "reference_client"
