"""Dérivation d'un `label` (clé machine snake_case) depuis un `title` en
langage naturel — pour que le script d'optimisation de prompts DSPy
(`scripts/dspy_prompt_tuning.py`) régénère `label` en cohérence avec un
nouveau `Nom` proposé (voir tasks/plan-dspy-prompt-tuning.md), même si le
LLM ne voit jamais `label`.
"""

import unicodedata

# Articles/prépositions français très courts qui n'apportent rien au label
# (voir les labels existants dans tests/data/gold_devis_fields.csv : "Nom de
# la société" -> "nom_societe", "Pourcentage d'acompte" -> "pourcentage_acompte").
_STOPWORDS = {"de", "du", "des", "la", "le", "les", "l", "d", "un", "une", "et", "au", "aux", "a"}


def slugify_title(title: str) -> str:
    """snake_case ASCII dérivé de `title` : accents retirés, minuscules,
    articles/prépositions courants filtrés, tout caractère non alphanumérique
    ASCII traité comme séparateur (y compris apostrophes typographiques,
    jamais simplement supprimées — sinon "d'acompte" deviendrait "dacompte"
    au lieu de se scinder en "d"/"acompte")."""
    decomposed = unicodedata.normalize("NFKD", title)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    separated = "".join(c if c.isascii() and c.isalnum() else " " for c in without_accents)
    tokens = [t for t in separated.lower().split() if t not in _STOPWORDS]
    return "_".join(tokens)
