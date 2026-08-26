# Task List : Contexte textuel des candidats dans l'arbitrage de conflit

Plan : [tasks/plan-arbitration-candidate-context.md](plan-arbitration-candidate-context.md) ·
Spec : [specs/arbitration-candidate-context.md](../specs/arbitration-candidate-context.md)

---

## Task 1 : Injecter le snippet + page de chaque candidat dans le prompt d'arbitrage

**Description :** Propager `text` (texte source complet) de `_extract` vers
`_select_candidate` puis `_arbitrate`. Dans `_arbitrate`, calculer
`_locate(text, ...)` pour chaque candidat (pas seulement le gagnant) et
passer ce contexte à `_arbitration_text`, qui l'affiche sous la forme
`Candidat N : <valeur> (page X, contexte : "...snippet...")`. Mettre à jour
`_arbitration_example` pour refléter ce même format dans le few-shot.

**Acceptance criteria :**
- [x] `_arbitrate` reçoit le texte source et calcule un snippet + page pour
      chaque candidat avant de construire le prompt
- [x] `_arbitration_text` affiche ce contexte pour chaque candidat
- [x] `_arbitration_example` (few-shot) est cohérent avec le nouveau format
- [x] La sélection finale (`extraction_text` recopié mot pour mot par le
      LLM) continue de fonctionner sans changement de son contrat de sortie
- [x] Le repli sur la première occurrence en cas d'arbitrage imparsable
      reste inchangé

**Verification :**
- [x] Nouveau test offline dans `tests/test_ner_langextract_dedupe.py`
      (`test_extract_arbitration_prompt_includes_context_snippet_per_candidate`) :
      monkeypatch `langextract.extract`, deux candidats groundés à des
      positions différentes → assertion que `calls[1]["text_or_documents"]`
      contient le snippet et la page de chacun des deux candidats
- [x] Tests existants du fichier (notamment
      `test_extract_arbitrates_genuine_conflict_via_second_llm_call` et
      `test_extract_falls_back_to_first_occurrence_when_arbitration_is_unparseable`)
      passent sans modification de leurs assertions
- [x] `uv run pytest -m "not live"` : 148 passed, 1 deselected (hors
      `test_fields_routes.py`, échec préexistant lié à `DATASET GOLD.csv`
      modifié dans l'arbre de travail, sans rapport avec ce changement —
      confirmé en isolant ce fichier avec `git stash`)
- [ ] `uv run pytest -m live` revérifié manuellement si clé API disponible

**Dependencies :** None

**Files :**
- `app/tools/ner_langextract.py`
- `tests/test_ner_langextract_dedupe.py`

**Estimated scope :** S (2 fichiers)

---

## Checkpoint : Complete
- [x] `uv run pytest -m "not live"` passe intégralement (hors échec
      préexistant sans rapport, voir Task 1)
- [ ] Revue avec l'utilisateur
