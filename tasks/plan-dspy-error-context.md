# Plan : DSPy — Définition seule + contexte d'erreur enrichi

Intent confirmée par `idea-refine` (voir conversation, pas de doc séparé —
résumé ci-dessous). Chantier suivant sur la branche `feat/dspy-prompt-tuning`
(le premier chantier, `tasks/plan-dspy-prompt-tuning.md`, est terminé et
entièrement coché — celui-ci le complète, fichiers séparés pour ne pas
mélanger deux chantiers dans un seul doc).

## Vue d'ensemble

Trois changements combinés à `scripts/dspy_prompt_tuning.py` :

1. **Définition seule optimisée** — `Nom`/`label` ne sont plus jamais
   proposés/régénérés, toujours recopiés tels quels depuis le CSV
   d'origine. Simplification mécanique (retire une dimension), pas de
   nouvelle logique.
2. **Contexte d'erreur enrichi** — `FailureExample` gagne l'evidence de
   l'extraction (déjà calculée, gratuite) et l'evidence du gold (dérivée à
   la volée par recherche dans le markdown, jamais persistée). Le
   proposeur DSPy passe de `dspy.Predict` à `dspy.ChainOfThought` : le
   diagnostic du type d'erreur devient un raisonnement du modèle, pas un
   classifieur codé en dur.
3. **Suivi de progression** — `print()` par round et par candidat dans
   `optimize_field` (y compris le `reasoning` produit par ChainOfThought),
   pour voir l'optimisation avancer plutôt que d'attendre le résultat
   final.

Résumé de l'intent confirmée (via `idea-refine`, toutes les options
recommandées retenues) :
- Evidence gold dérivée à la volée (recherche substring dans le markdown),
  jamais backfillée dans `dataset_gold_devis.yaml`.
- Pas de classifieur d'erreur codé en dur — `dspy.ChainOfThought` fournit
  le diagnostic via son champ `reasoning` automatique.
- Pas d'utilitaire de localisation de texte partagé/réutilisable — logique
  interne à `scripts/dspy_prompt_tuning.py` (YAGNI, un seul appelant connu).
- `scripts/text_slug.py` : **supprimé** (décision tranchée ici, voir
  Architecture Decisions) — plus aucun appelant après ce chantier.

## Architecture Decisions

- **`scripts/text_slug.py` supprimé, pas gardé "au cas où"** : `grep`
  confirme `slugify_title` n'a jamais eu d'autre appelant que
  `scripts/dspy_prompt_tuning.py` (ni `app/`, ni un autre script). Une fois
  `label` non régénéré, c'est du code mort pur — le garder "pour plus
  tard" contredit les instructions du projet (pas d'abstraction
  spéculative). Supprimé avec son test (`tests/test_text_slug.py`).
- **`FieldCandidate` perd `title`, gagne `reasoning` (Tâche 5)** : pas
  aplati en `list[str]` malgré la simplification — le `reasoning` produit
  par `dspy.ChainOfThought` est la donnée qui justifie le point 3 (suivi de
  progression : voir *pourquoi* un candidat a été proposé, pas seulement
  son F1). L'aplatir en `list[str]` à la Tâche 1 puis devoir réintroduire
  une structure à la Tâche 5 serait un aller-retour inutile — la Tâche 1
  laisse `FieldCandidate(definition: str)` (un seul champ, pas encore de
  `reasoning`), la Tâche 5 lui ajoute `reasoning: str`.
- **`current_title` reste une entrée du prompt, mais plus une sortie** :
  `ProposeFieldPrompt` garde `current_title` en `InputField` (contexte —
  le LLM doit savoir quel champ il définit) et perd `new_title` en
  `OutputField`. Sans ce contexte, une définition reformulée risquerait de
  dériver sémantiquement du concept nommé par le `Nom` actuel.
- **`score_field_candidate` perd `candidate_title`** : le lookup du
  résultat dans la réponse de `ner_extractor.extract` se fait désormais
  par `r.field_title == target_field.title` (le titre ne varie plus, donc
  toujours celui du CSV d'origine) au lieu de `candidate_title`.
- **Evidence gold : recherche substring ±80 caractères, avec limites de
  frontière de mot pour les valeurs purement alphanumériques** : même
  convention de contexte que `_locate` côté extraction
  (`app/tools/ner_langextract.py`, `_CONTEXT_CHARS = 80`,
  `PAGE_SEPARATOR_RE` réutilisé pour nettoyer le snippet). `\b...\b` pour
  éviter qu'une valeur courte comme `"30"` ne matche à l'intérieur de
  `"1030"` — mitigation simple, pas un vrai matching grounded (LangExtract
  ne peut pas être réutilisé ici : il n'y a pas de second appel LLM pour
  grounder une valeur gold, seulement une recherche texte). Non trouvée
  (valeur paraphrasée/reformatée) → `None`, cas attendu et documenté, pas
  une erreur.
- **`FieldResult` minimal** : `field_key`, `baseline_definition`,
  `best_definition`, `baseline_f1`, `best_f1` — `baseline_title` retiré
  (le titre ne varie jamais, il est toujours `field.title`, pas besoin de
  le porter dans le résultat). Le `reasoning` du candidat gagnant n'est
  **pas** persisté dans `FieldResult`/le CSV — visible en direct via la
  Tâche 6 (stdout), pas needed après coup ; garder le CSV de sortie stable
  (mêmes colonnes que `gold_devis_fields.csv`).
- **Suivi de progression = `print()` direct, pas de framework de
  logging** : cohérent avec le reste de `scripts/` (`gold_dataset_sync.py`,
  `validate_ocr_tuning.py`) — aucun logger structuré ailleurs dans le repo.
- **API DSPy vérifiée avant d'écrire ce plan** (Documentation First,
  `dspy==3.3.1` installé) :
  - `dspy.ChainOfThought(Signature)` ajoute automatiquement un champ de
    sortie `reasoning` — pas besoin de le déclarer dans la Signature.
  - `dspy.utils.DummyLM(answers=[{...}])` **doit** inclure la clé
    `reasoning` dans chaque dict de réponse quand le `Predict` sous-jacent
    est un `ChainOfThought` — omise, `DummyLM` lève `AdapterParseError`
    ("Expected to find output fields in the LM response: [reasoning,
    ...]"), vérifié en réel avant d'écrire les tâches.

## Ordre d'implémentation

Slicing vertical : d'abord la simplification mécanique (Tâche 1, aucune
nouvelle logique, réduit la surface avant d'ajouter du contexte),
puis l'enrichissement du contexte d'erreur pièce par pièce (evidence
extraction → evidence gold → format du résumé → ChainOfThought), puis le
suivi de progression (consomme le `reasoning` de la tâche précédente),
puis la validation réelle bornée.

### Phase 1 : Définition seule (mécanique)
- [x] Tâche 1 : retirer `Nom`/`label` de la cible d'optimisation +
      supprimer `scripts/text_slug.py`

### Checkpoint 1
- [x] `uv run pytest -m "not live"` passe

### Phase 2 : Contexte d'erreur enrichi
- [x] Tâche 2 : `FailureExample.extracted_evidence` (déjà calculé, simple
      plomberie)
- [x] Tâche 3 : `FailureExample.gold_evidence` (recherche dans le markdown,
      nouvelle logique)
- [x] Tâche 4 : `_format_failure_summary` — bloc structuré Gold/Evidence
      gold/Extraction incorrecte/Evidence extraction
- [x] Tâche 5 : `ProposeFieldPrompt`/`propose_candidates` →
      `dspy.ChainOfThought`, `FieldCandidate.reasoning`

### Checkpoint 2
- [x] `uv run pytest -m "not live"` passe ; testé avec `dspy.utils.DummyLM`
      (réponses incluant `reasoning`), aucun appel réseau

### Phase 3 : Suivi de progression + validation réelle
- [x] Tâche 6 : `print()` par round/candidat (F1 + `reasoning`) dans
      `optimize_field`
- [x] Tâche 7 : run réel de validation borné (1 champ, budget réduit) —
      vérifie qu'au moins une `gold_evidence` réelle est trouvée et qu'un
      `reasoning` non vide est produit

### Checkpoint final
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] Tâche 7 exécutée avec succès
- [ ] Revue avec l'utilisateur
- [ ] Proposer `/code-review-and-quality` puis une PR une fois la branche
      complète (convention CLAUDE.md)

## Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| La recherche substring ne trouve la `gold_evidence` que pour une minorité de documents (valeurs souvent paraphrasées/reformatées dans le texte réel) | Moyen (le bénéfice du contexte enrichi serait plus faible qu'espéré) | `None` géré proprement (ligne omise) plutôt que de bloquer ; mesuré concrètement à la Tâche 7 (run réel) — pas suppposé a priori |
| Une valeur gold courte/numérique matche une sous-chaîne non pertinente (ex. `"30"` dans `"1030"`) malgré les limites `\b` | Faible | `\b` déjà prévu pour les valeurs purement alphanumériques ; documenté comme limite connue, pas un vrai grounding |
| `dspy.ChainOfThought` change le format de réponse attendu par `DummyLM` — un test qui oublierait la clé `reasoning` casserait silencieusement (erreur d'adapter, pas un assert clair) | Faible (déjà vérifié avant d'écrire ce plan) | Vérifié en réel avant codage (voir Architecture Decisions) ; les tests de la Tâche 5 incluent explicitement `reasoning` dans chaque `DummyLM(answers=[...])` |
| Suppression de `scripts/text_slug.py` perd un utilitaire qui pourrait resservir plus tard (ex. si l'optimisation de `Nom` revient) | Faible | Réversible via `git log`/`git revert` si le besoin réapparaît — pas de raison de garder du code mort en attendant un besoin hypothétique |

## Open Questions

Aucun bloquant restant — l'intent a été entièrement tranchée via
`idea-refine`. Hors scope explicite (voir "Not Doing" de l'idée) :
classifieur d'erreur codé en dur, backfill de `evidence.text` dans le YAML
gold, utilitaire de localisation de texte partagé, réoptimisation future de
`Nom`.
