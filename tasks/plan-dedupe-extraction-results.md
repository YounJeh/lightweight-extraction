# Plan : Déduplication des résultats d'extraction

Spec : [specs/dedupe-extraction-results.md](../specs/dedupe-extraction-results.md)

## Composants touchés

- `app/tools/ner_langextract.py` — seul point de changement de logique
  (filtrage + déduplication avant construction des `ExtractionResult`).
- `tests/test_ner_langextract_live.py` ou un nouveau fichier
  `tests/test_ner_langextract_dedupe.py` — test offline avec
  `langextract.extract` monkeypatché.

Aucune dépendance externe à ajouter, aucun autre fichier à toucher (voir
Boundaries de la spec).

## Ordre d'implémentation

Une seule tâche : le fix et son test sont trop couplés pour être séparés
utilement (le test valide directement le comportement du fix).

## Risques

- Le monkeypatch doit reproduire fidèlement la forme réelle de
  `annotated.extractions` (`data.Extraction` / `data.CharInterval`) pour
  rester représentatif — vérifié par lecture directe de la lib installée
  (déjà fait, voir spec).
- Le choix « première occurrence par position » est une décision produit ;
  documentée comme point ouvert dans la spec plutôt que bloquante.

## Checkpoint

- [ ] `uv run pytest -m "not live"` passe intégralement, nouveau test inclus
- [ ] Revue avec l'utilisateur
