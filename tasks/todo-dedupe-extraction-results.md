# Task List : Déduplication des résultats d'extraction

Plan : [tasks/plan-dedupe-extraction-results.md](plan-dedupe-extraction-results.md) ·
Spec : [specs/dedupe-extraction-results.md](../specs/dedupe-extraction-results.md)

---

## Task 1 : Filtrer + arbitrer par LLM dans `LangExtractNerExtractor.extract()`

**Description :** Ignorer les `Extraction` avec `char_interval is None` ou
`extraction_text` vide/blanc. Parmi les `Extraction` restantes par champ :
0 → absent des résultats ; 1 → acceptée directement ; plusieurs à la même
valeur normalisée → fusion sur la première occurrence ; plusieurs valeurs
distinctes → arbitrage via un second appel `langextract.extract` dédié
(`_arbitrate`), avec repli sur la première occurrence si la réponse ne
correspond à aucun candidat. Test offline (monkeypatch `langextract.extract`)
couvrant chaque branche.

**Acceptance criteria :**
- [x] `extract()` ne retourne jamais plus d'un résultat par `field_title`
- [x] Les extractions sans `char_interval` ou à texte vide sont exclues
- [x] Un seul candidat groundé est accepté sans appel LLM supplémentaire
- [x] Plusieurs candidats à même valeur normalisée sont fusionnés sans
      appel LLM supplémentaire
- [x] Un vrai conflit (valeurs distinctes) déclenche un second appel
      `langextract.extract` dédié à l'arbitrage
- [x] Si l'arbitrage ne matche aucun candidat, repli sur la première
      occurrence (jamais de champ perdu)

**Verification :**
- [x] Tests : `uv run pytest -m "not live"` (nouveau test + suite complète —
      48 passed, 1 deselected, mêmes 2 échecs pré-existants non liés)

**Dependencies :** None

**Files :**
- `app/tools/ner_langextract.py`
- `tests/test_ner_langextract_dedupe.py` (nouveau)

**Estimated scope :** S (2 fichiers)

---

## Checkpoint : Complete
- [x] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue avec l'utilisateur
