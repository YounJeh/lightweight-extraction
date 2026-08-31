# Task List : DSPy — Définition seule + contexte d'erreur enrichi

Plan : [tasks/plan-dspy-error-context.md](plan-dspy-error-context.md)

---

## Task 1 : retirer `Nom`/`label` de la cible d'optimisation + supprimer `scripts/text_slug.py`

**Description :** Dans `scripts/dspy_prompt_tuning.py` :
1. `FieldCandidate` : ne garde que `definition: str` (retire `title`).
2. `ProposeFieldPrompt` : retire l'`OutputField` `new_title` — garde
   `current_title` en `InputField` (contexte, jamais optimisé).
3. `propose_candidates` : construit `FieldCandidate(definition=result.new_definition)`
   uniquement, n'accède plus à `result.new_title`.
4. `score_field_candidate` : signature perd `candidate_title` (ne reste
   que `candidate_definition`) ; la copie de `fields` ne met à jour que
   `definition` (`f.model_copy(update={"definition": candidate_definition})`) ;
   le lookup du résultat devient
   `next((r for r in results if r.field_title == target_field.title), None)`
   (le titre ne varie plus, toujours celui du CSV d'origine).
5. `optimize_field` : la fonction interne `score(...)` ne prend plus que
   `definition` ; la boucle appelle `score(candidate.definition)` ; plus de
   `best_title` à traquer, seulement `best_definition`.
6. `FieldResult` : retire `baseline_title`, `best_title`, `best_label`.
7. `_field_csv_row`/`write_results_csv` : `label`/`title` ne sont plus des
   paramètres — toujours `field.key`/`field.title` ; seul `definition`
   varie selon la présence d'un résultat.
8. Docstring de module (haut de fichier) : "des valeurs `Nom`/`Définition`"
   -> "de la `Définition`".
9. Supprimer `scripts/text_slug.py` et `tests/test_text_slug.py` (plus
   aucun appelant après ce changement — voir Architecture Decisions du
   plan).

**Acceptance criteria :**
- [x] `score_field_candidate("numero_devis", "nouvelle def", all_fields=...,
      ...)` (signature à 2 positionnels, plus 3) fonctionne et le `title`
      envoyé à `ner_extractor.extract` pour ce champ est **inchangé**
      (celui du CSV d'origine)
- [x] `optimize_field(...)` renvoie un `FieldResult` sans `title`/`label`,
      avec `best_definition` différent de `baseline_definition` quand un
      candidat gagne
- [x] `write_results_csv(...)` produit un CSV où **toutes** les lignes ont
      `Nom`/`label` identiques à l'entrée (`all_fields`), y compris les
      champs optimisés — seule `Définition` diffère pour ceux-là
- [x] `scripts/text_slug.py` et `tests/test_text_slug.py` n'existent plus ;
      `uv run pytest --collect-only` ne référence plus aucun test de ce
      module

**Verification :**
- [x] Tests : `uv run pytest -m "not live" tests/test_dspy_prompt_tuning.py -q`
      (tests existants adaptés aux nouvelles signatures — plus de
      `title`/`label` dans les assertions/fixtures)

**Dependencies :** None

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`
- `scripts/text_slug.py` (supprimé)
- `tests/test_text_slug.py` (supprimé)

**Estimated scope :** M (large en lignes touchées mais mécanique — retire
une dimension, aucune nouvelle logique)

---

## Checkpoint : Phase 1
- [x] `uv run pytest -m "not live"` passe

---

## Task 2 : `FailureExample.extracted_evidence`

**Description :** Dans `score_field_candidate`, `extracted.text_position`
(déjà calculé par `LangExtractNerExtractor._locate`, jamais recalculé ici)
devient `FailureExample.extracted_evidence: str | None` — `None` quand
`extracted` est `None` (rien n'a été extrait pour ce document) ou que
`extracted.text_position` est lui-même `None`.

**Acceptance criteria :**
- [ ] Un `FailureExample` généré pour un document où `extracted` a un
      `text_position` non vide porte ce texte dans `extracted_evidence`
- [ ] Un document sans extraction (`extracted is None`) produit
      `extracted_evidence=None`, pas d'exception

**Verification :**
- [ ] Tests : `uv run pytest -m "not live" tests/test_dspy_prompt_tuning.py -k extracted_evidence`

**Dependencies :** Task 1

**Files likely touchés :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** XS (plomberie, donnée déjà disponible)

---

## Task 3 : `FailureExample.gold_evidence`

**Description :** Nouvelle fonction interne `_find_gold_evidence(markdown:
str, gold_value: object, *, context_chars: int = 80) -> str | None` dans
`scripts/dspy_prompt_tuning.py` : recherche `str(gold_value)` dans
`markdown` (insensible à la casse ; `\b...\b` autour du motif si
`gold_value` est purement alphanumérique, pour limiter les faux positifs
sur les valeurs courtes — voir Architecture Decisions du plan), renvoie un
snippet `±context_chars` autour du match nettoyé des séparateurs de page
(réutilise `PAGE_SEPARATOR_RE` de `app/tools/pdf_pymupdf4llm.py`, même
convention que `_locate` dans `ner_langextract.py`). `None` si non trouvée.
Appelée dans `score_field_candidate` au moment de construire chaque
`FailureExample`, avec le `markdown` déjà chargé pour ce document (pas de
rechargement).

**Acceptance criteria :**
- [ ] `_find_gold_evidence("...sous 30 jours après réception...", "30
      jours")` renvoie un snippet contenant `"30 jours"` et son contexte
- [ ] `_find_gold_evidence("...un texte sans le rapport...", "30 jours")`
      renvoie `None`
- [ ] `_find_gold_evidence("...page 1030...", "30")` **ne matche pas**
      `"30"` à l'intérieur de `"1030"` (frontière de mot respectée)
- [ ] Un `FailureExample` généré via `score_field_candidate` porte le
      `gold_evidence` correspondant quand trouvé

**Verification :**
- [ ] Tests : `uv run pytest -m "not live" tests/test_dspy_prompt_tuning.py -k gold_evidence`

**Dependencies :** Task 2

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** S (nouvelle logique, mais isolée et pure)

---

## Task 4 : `_format_failure_summary` — bloc structuré

**Description :** Reformater `_format_failure_summary` pour produire, par
document en échec, un bloc proche de l'exemple donné par l'utilisateur :

```
- {source_file} :
  Gold : {gold_value}
  Evidence gold : "{gold_evidence}"          (ligne omise si None)
  Extraction incorrecte : {extracted_value}
  Evidence extraction : "{extracted_evidence}" (ligne omise si None)
```

Chaîne vide (`""`) si `failures` est vide, comme aujourd'hui.

**Acceptance criteria :**
- [ ] Un `FailureExample` avec les deux evidences produit un bloc avec les
      4 lignes (Gold/Evidence gold/Extraction incorrecte/Evidence
      extraction)
- [ ] Un `FailureExample` avec `gold_evidence=None` omet la ligne
      "Evidence gold" sans laisser de ligne vide/`None` littéral
- [ ] `failures=[]` renvoie toujours `""`

**Verification :**
- [ ] Tests : `uv run pytest -m "not live" tests/test_dspy_prompt_tuning.py -k format_failure_summary`

**Dependencies :** Task 2, Task 3

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** S (formatage pur, plusieurs cas de test)

---

## Task 5 : `ProposeFieldPrompt`/`propose_candidates` → `dspy.ChainOfThought`

**Description :** `dspy.Predict(ProposeFieldPrompt)` -> `dspy.ChainOfThought
(ProposeFieldPrompt)` dans `propose_candidates`. `FieldCandidate` gagne
`reasoning: str` (en plus de `definition`, voir Tâche 1) — peuplé depuis
`result.reasoning` (champ automatique de `ChainOfThought`, pas déclaré
dans la Signature). Docstring de `ProposeFieldPrompt` mise à jour pour
inviter explicitement le diagnostic avant la reformulation (ex. "Identifie
d'abord la confusion probable à partir des deux evidences avant de
proposer une nouvelle définition qui la rend impossible").

**Acceptance criteria :**
- [ ] Avec un `dspy.utils.DummyLM(answers=[{"reasoning": "...", "new_definition": "..."}])`
      (la clé `reasoning` est **obligatoire** dans chaque réponse factice —
      vérifié en amont, voir Architecture Decisions), `propose_candidates`
      renvoie des `FieldCandidate` avec `reasoning` et `definition` non
      vides
- [ ] Le prompt envoyé au LM factice (`lm.history[0]["messages"]`) contient
      toujours `current_title` (contexte) même si `title` n'est plus
      optimisé
- [ ] Un test avec une réponse `DummyLM` **sans** clé `reasoning` échoue
      explicitement (documente la contrainte, évite qu'un futur test
      l'oublie silencieusement)

**Verification :**
- [ ] Tests : `uv run pytest -m "not live" tests/test_dspy_prompt_tuning.py -k propose_candidates`
      — LM factice uniquement, aucun appel réseau

**Dependencies :** Task 4

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** S (changement de classe DSPy + un champ de donnée)

---

## Checkpoint : Phase 2
- [ ] `uv run pytest -m "not live"` passe ; `ProposeFieldPrompt` testé avec
      `dspy.utils.DummyLM` (réponses avec `reasoning`), aucun appel réseau

---

## Task 6 : suivi de progression — `print()` par round/candidat

**Description :** Dans `optimize_field` (`scripts/dspy_prompt_tuning.py`) :
1. Au début : `print(f"[{field_key}] baseline F1={baseline_score.f1:.3f} ({len(baseline_score.failures)} échec(s))")`.
2. La boucle `for _ in range(n_rounds):` devient
   `for round_idx in range(1, n_rounds + 1):`, avec
   `print(f"[{field_key}] round {round_idx}/{n_rounds} : {n_candidates} candidat(s) proposé(s)")`.
3. La boucle candidats devient `for i, candidate in enumerate(candidates, start=1):`,
   avec `print(f"[{field_key}]   candidat {i}/{n_candidates} : F1={candidate_score.f1:.3f}{" (nouveau meilleur)" if candidate_score.f1 > best_score.f1 else ""} — {candidate.reasoning[:120]}")`
   (raisonnement tronqué pour rester lisible en console).

Aucun changement de signature/valeur de retour — uniquement des `print()`
ajoutés dans le corps existant.

**Acceptance criteria :**
- [ ] Avec `score_fn`/`propose_fn` factices (mêmes patterns que les tests
      `optimize_field` existants) et `capsys`, la sortie stdout contient le
      `field_key`, au moins une ligne "round X/Y", et au moins une ligne
      "candidat i/n" avec un F1 affiché
- [ ] Quand un candidat devient le nouveau meilleur, la ligne
      correspondante le signale ("nouveau meilleur" ou équivalent)
- [ ] Le comportement de retour (`FieldResult`) est strictement inchangé
      par rapport à avant cette tâche (tests `optimize_field` existants
      toujours verts sans modification de leurs assertions sur la valeur
      de retour)

**Verification :**
- [ ] Tests : `uv run pytest -m "not live" tests/test_dspy_prompt_tuning.py -k optimize_field`

**Dependencies :** Task 1, Task 5

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** S (ajout de `print()`, pas de nouvelle logique)

---

## Task 7 : run réel de validation borné

**Description :** Exception CLAUDE.md (DSPy) toujours en vigueur — run réel
autorisé. Lancer `scripts/dspy_prompt_tuning.py` sur un champ, budget
réduit (même approche que Task 9 du chantier précédent : script ad hoc
dans le scratchpad, `gold_documents` limité à quelques documents pour
maîtriser le coût). Objectif : vérifier que le pipeline enrichi fonctionne
sur de vraies données, pas seulement des doubles — en particulier que
`_find_gold_evidence` (Tâche 3) trouve effectivement des evidences sur du
texte réel (pas juste sur les exemples synthétiques des tests) et que
`reasoning` (Tâche 5) n'est jamais vide.

**Acceptance criteria :**
- [ ] Le run se termine sans exception
- [ ] Au moins un `FailureExample` réel (sur les documents choisis) a un
      `gold_evidence` non `None` — sinon la Tâche 3 n'apporte rien en
      pratique sur ce jeu de test, à documenter comme risque avéré plutôt
      que supposé
- [ ] Le `reasoning` affiché par la Tâche 6 est non vide et lisible
      (pas un texte tronqué à 0 caractère ni un artefact de formatage)
- [ ] Le CSV de sortie a `Nom`/`label` identiques à `gold_devis_fields.csv`
      pour tous les champs, seule `Définition` diffère pour le(s) champ(s)
      demandé(s)

**Verification :**
- [ ] Exécution manuelle du script (pas un test `pytest` — run réel,
      volontairement hors suite automatisée)

**Dependencies :** Task 6

**Files likely touched :**
- Aucun fichier de code (run de validation)

**Estimated scope :** XS (pas de code, exécution + lecture des résultats)

---

## Checkpoint final
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Tâche 7 exécutée avec succès
- [ ] Revue avec l'utilisateur
- [ ] Proposer `/code-review-and-quality` puis une PR une fois la branche
      complète (convention CLAUDE.md)
