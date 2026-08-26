# Plan : Contexte textuel des candidats dans l'arbitrage de conflit

Spec : [specs/arbitration-candidate-context.md](../specs/arbitration-candidate-context.md)

## Composants touchés

- `app/tools/ner_langextract.py` — seul point de changement de logique :
  propagation de `text` jusqu'à `_arbitrate`, calcul du snippet/page par
  candidat, mise à jour de `_arbitration_text` et `_arbitration_example`.
- `tests/test_ner_langextract_dedupe.py` — nouveau test offline, dans la
  continuité des tests d'arbitrage déjà présents dans ce fichier.

Aucune dépendance externe à ajouter, aucun autre fichier à toucher (voir
Boundaries de la spec).

## Ordre d'implémentation

Une seule tâche : le changement de signature (`_select_candidate` →
`_arbitrate`), le nouveau format de prompt et son test sont trop couplés
pour être séparés utilement — le test valide directement le format produit
par le changement de signature.

## Risques

- Propager `text` change la signature interne de `_select_candidate` et
  `_arbitrate` (fonctions privées du module, pas de contrat externe) —
  aucun impact sur `Protocol NerExtractor` ni sur les appelants hors module.
- Le few-shot (`_arbitration_example`) doit être mis à jour en cohérence
  avec le nouveau format de `_arbitration_text`, sinon le LLM pourrait
  recopier le format `(page X, contexte : "...")` dans sa réponse au lieu
  de la valeur seule — à couvrir explicitement par le test offline (assertion
  sur `extraction_text` de la sélection, pas juste sur le prompt envoyé).
- `_locate` est appelé N fois de plus par arbitrage (une fois par candidat
  au lieu d'une fois pour le gagnant) — coût négligeable (fonction pure sur
  du texte déjà en mémoire, pas d'appel réseau).

## Checkpoint

- [ ] `uv run pytest -m "not live"` passe intégralement, nouveau test inclus
- [ ] Revue avec l'utilisateur
