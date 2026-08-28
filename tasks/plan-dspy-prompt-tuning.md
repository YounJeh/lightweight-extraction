# Plan : Optimisation des prompts NER (Nom/Définition) via DSPy

Intent confirmée par `interview-me` (voir conversation, pas de doc séparé —
résumé ci-dessous). Branche : `feat/dspy-prompt-tuning`.

## Vue d'ensemble

Un script hors-ligne (`scripts/dspy_prompt_tuning.py`), jamais intégré à
l'app en production, qui explore — **un champ à la fois** — de meilleures
formulations de `Nom`/`Définition` pour chaque champ de
`tests/data/gold_devis_fields.csv`, via DSPy (proposition de variantes) +
le pipeline réel (`PyMuPDF4LlmTextExtractor` + `LangExtractNerExtractor`)
scoré en F1 contre `tests/data/dataset_gold_devis.yaml`. Pendant
l'optimisation d'un champ, les 6 autres restent figés à leur valeur CSV
actuelle (LangExtract reçoit toujours tous les champs dans un seul appel).
Un cache markdown local évite de refaire le PDF→markdown à chaque essai.
Sortie : un nouveau CSV (même format que `gold_devis_fields.csv`, jamais
d'écrasement) que l'utilisateur applique lui-même.

Résumé de l'intent confirmée :
- Cible d'optimisation : `Nom`/`Définition` uniquement. `label` régénéré en
  cohérence (slug du nouveau `Nom`) bien que sans effet sur le LLM.
  Instruction globale fixe et few-shot (`Exemple texte`/`exemple valeur`)
  inchangés — hors scope.
- Optimisation field-par-field, jamais jointe.
- Métrique : F1 par champ, définition identique à
  `scripts/gold_dataset_eval.py` (`_precision_recall_f1`).
- Aucune écriture sur `gold_devis_fields.csv` ni la DB — sortie = nouveau
  fichier seulement.
- **Run réel autorisé pour ce chantier** — CLAUDE.md pose en général "Ne
  fais pas de run de vérification sur le corpus gold. C'est uniquement à
  l'humain de le faire.", mais porte désormais une exception explicite pour
  tout ce qui touche à DSPy : je peux exécuter le script (Task 8/9) contre
  le vrai `tests/data/dataset_gold_devis.yaml`, appels LLM réels compris
  (LangExtract *et* DSPy). Les tests automatisés (`pytest`) restent malgré
  tout sur des doubles (fakes) — pas pour respecter une interdiction, mais
  pour rester rapides/déterministes/gratuits en CI ; l'exécution réelle est
  un run délibéré du script, pas quelque chose qui doit se produire au fil
  de `pytest -m "not live"`.

## Architecture Decisions

- **`precision_recall_f1` promu dans `scripts/gold_matching.py`** :
  actuellement privé (`_precision_recall_f1`) dans
  `scripts/gold_dataset_eval.py`. Le script DSPy a besoin de la même
  définition — plutôt que dupliquer ou importer un symbole privé
  cross-module, on le rend public dans `gold_matching.py` (qui contient déjà
  toute la logique de matching/classification réutilisée par les deux
  scripts) et `gold_dataset_eval.py` l'importe de là. Changement mécanique,
  aucun changement de comportement.
- **Cache markdown : fichiers plats par `source_file`, pas de hash**
  (`scripts/_dspy_markdown_cache/<source_file>.md`, gitignoré). Même pattern
  que `scripts/_ocr_tuning_cache/` (`scripts/validate_ocr_tuning.py:123`) —
  les PDF de `data_test/` ne changent pas pendant une session d'optimisation,
  pas besoin d'invalidation par contenu. Si un PDF change, l'utilisateur
  vide le cache à la main.
- **Optimisation field-par-field = boucle custom, pas un teleprompter DSPy
  standard (COPRO/MIPRO)** : ces teleprompters optimisent l'instruction
  d'un `dspy.Predict` dont c'est *DSPy lui-même* qui exécute l'appel LLM de
  la tâche. Ici, la tâche réelle passe par LangExtract (un point d'accès LLM
  externe à DSPy, avec son propre chunking/grounding/arbitrage — voir
  `choix_techniques.md`), pas par un module DSPy. On utilise donc DSPy pour
  la partie où il apporte de la valeur (un `dspy.Signature`/`dspy.Predict`
  qui *propose* N variantes de `title`/`definition` à partir de la valeur
  actuelle + des échecs observés), et une boucle d'évaluation maison qui
  score chaque variante via le vrai pipeline + `gold_matching`. Documenté
  explicitement pour qu'un futur lecteur ne s'attende pas à du COPRO/MIPRO
  "standard".
- **`label` dérivé par slug, jamais proposé par le LLM** : fonction pure
  `slugify_title(title: str) -> str` (`scripts/text_slug.py` — accents
  retirés, minuscules, articles/prépositions courants filtrés — `de`, `du`,
  `la`, `l`, `d`..., séparateurs → `_`), testée isolément contre les
  `label` existants (`numero_devis`, `nom_societe`,
  `pourcentage_acompte`...) pour vérifier qu'un `title` inchangé reproduit
  le `label` actuel. **Écart documenté et accepté :**
  `slugify_title("Délai de paiement du solde") == "delai_paiement_solde"`,
  alors que le label existant est `delai_paiement_solde_jours` — le suffixe
  `_jours` encode l'unité (jours) sans être un mot du `title`, un ajout
  humain non dérivable mécaniquement. Le CSV de sortie porte donc ce `label`
  légèrement différent pour ce champ tant que son `title` n'est pas modifié
  pour l'inclure ; l'utilisateur le voit avant d'appliquer.
- **Réutilisation du routing modèle existant** : `dspy.LM` est configuré à
  partir de `LLM_MODEL`/`_is_openai_model`/`_api_key_for` déjà présents dans
  `app/tools/ner_langextract.py` (import direct, comme
  `scripts/validate_ocr_tuning.py` importe déjà `_normalize_text` de
  `gold_matching`) — pas de deuxième logique de routing provider/clé à
  maintenir.
- **`pytest.mark.live` réutilisé tel quel** pour tout test qui appellerait
  un vrai LLM (LangExtract *ou* DSPy) — pas de nouveau marker : sa
  description actuelle ("appelle un vrai LLM (Gemini) via LangExtract")
  couvre déjà l'esprit ; tous les tests unitaires de ce chantier tournent
  avec de faux extracteurs/LM (mêmes patterns que
  `tests/test_gold_dataset_eval.py` — `_FakePdfExtractor`, extracteurs
  injectés) et passent sous `-m "not live"`. Ça reste vrai même si le run
  réel du script en dehors de `pytest` est désormais autorisé (voir Vue
  d'ensemble) : la suite `pytest` par défaut ne doit jamais dépendre d'une
  clé API ou d'un accès réseau.
- **Sortie = CSV complet au format `gold_devis_fields.csv`** (mêmes
  colonnes : `section,label,Nom,Définition,Type,exemple valeur,Exemple
  texte,source`), écrit dans `tasks/dspy-prompt-tuning-results.csv` (chemin
  par défaut, overridable en CLI) — copiable-collable tel quel par-dessus le
  fichier existant. `baseline_f1`/`best_f1` par champ affichés sur stdout en
  fin de run (pas dans le CSV, pour ne pas polluer un format que
  `import_fields` doit pouvoir reparser tel quel).

## Ordre d'implémentation

Slicing vertical : d'abord les briques testables sans LLM (cache, slug,
metric promue), puis le scoring bout-en-bout avec de faux extracteurs
(prouve que la boucle d'évaluation est correcte avant d'y brancher DSPy),
puis DSPy (proposition de variantes, avec un faux LM en test), puis la
boucle d'optimisation + le CLI/export qui assemble tout.

### Phase 1 : Fondations sans LLM
- [ ] Tâche 1 : promouvoir `precision_recall_f1` dans `gold_matching.py`
- [ ] Tâche 2 : `scripts/dspy_markdown_cache.py` — cache disque par
      `source_file`
- [ ] Tâche 3 : `slugify_title` — dérivation du `label` depuis `Nom`

### Checkpoint 1
- [ ] `uv run pytest -m "not live"` passe

### Phase 2 : Scoring d'un champ (sans DSPy)
- [ ] Tâche 4 : `score_field_candidate` — F1 d'un champ pour un
      `title`/`definition` candidat, contre le dataset gold, avec un
      extracteur NER injecté (faux en test)

### Checkpoint 2
- [ ] `uv run pytest -m "not live"` passe ; `score_field_candidate` prouvé
      correct avec un faux extracteur déterministe (TP/FP/FN connus à la
      main)

### Phase 3 : Proposition de variantes via DSPy
- [ ] Tâche 5 : ajout de la dépendance `dspy` + configuration du `dspy.LM`
      (routing réutilisé depuis `ner_langextract`)
- [ ] Tâche 6 : `propose_candidates` — `dspy.Signature`/`dspy.Predict` qui
      propose N variantes `title`/`definition` à partir de la valeur
      actuelle + des documents en échec

### Checkpoint 3
- [ ] `uv run pytest -m "not live"` passe ; `propose_candidates` testé avec
      un LM factice (pas d'appel réseau)

### Phase 4 : Boucle d'optimisation + CLI/export
- [ ] Tâche 7 : `optimize_field` — orchestre baseline → proposition →
      scoring → meilleure variante (éventuellement plusieurs rounds)
- [ ] Tâche 8 : CLI `main()` — parcourt les champs demandés, écrit le CSV de
      sortie + résumé stdout

### Checkpoint 4
- [ ] `uv run pytest -m "not live"` passe intégralement (tout le chantier
      reste couvert par des doubles à ce stade)

### Phase 5 : Exécution réelle de validation
- [ ] Tâche 9 : lancer `scripts/dspy_prompt_tuning.py` pour de vrai (clé API
      requise dans l'environnement), sur un champ (`--field`), avec un
      budget réduit (`--n-candidates`/`--n-rounds` petits) — objectif :
      valider que le pipeline bout-en-bout tourne sans erreur et produit un
      `best_f1` cohérent (pas de crash, pas de F1 aberrant type `1.0`
      suspect ou `0.0` sur tous les candidats). Un run complet (tous les
      champs, budget de recherche plus large) reste au choix de
      l'utilisateur — coût en appels LLM proportionnel au budget, décision
      qui lui revient même si l'exécution en elle-même est désormais permise.

### Checkpoint final
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Tâche 9 exécutée avec succès (voir critères ci-dessus)
- [ ] Revue avec l'utilisateur
- [ ] Proposer `/code-review-and-quality` puis une PR une fois la branche
      complète (convention CLAUDE.md)

## Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| API DSPy (`dspy.LM`, signatures d'optimisation d'instructions, utilitaire de LM factice pour les tests) mal connue/obsolète en mémoire | Moyen (code qui ne compile pas ou API halluciné) | Vérifier l'API réelle contre la version installée (`uv pip show dspy` / doc du package) avant d'écrire les Tâches 5-6, même principe "Documentation First" que `scripts/gold_dataset_sync.py` |
| Un test `pytest` appellerait par erreur un vrai LLM (LangExtract ou DSPy), consommant du quota et cassant en CI sans clé | Élevé | Tout test de ce chantier utilise un extracteur/LM factice injecté ; le run réel (Tâche 9) est un appel explicite du script, jamais un test `pytest` |
| Un run réel de validation (Tâche 9) mal borné (budget élevé, tous les champs) consomme des appels LLM inutiles | Faible/Moyen | Tâche 9 bornée explicitement (1 champ, petit `n_candidates`/`n_rounds`) — un run complet plus coûteux reste une décision de l'utilisateur |
| Un test qui lirait/écrirait par erreur le vrai `tests/data/dataset_gold_devis.yaml` ou `tests/data/gold_devis_fields.csv` | Élevé | Réutiliser le pattern déjà en place (`load_gold_fields`/`_load_gold_documents` chargés une fois, jamais réécrits ; toute écriture de test cible `tmp_path`) |
| Un champ dont aucune annotation gold n'est renseignée (valeur `null` partout) donne un F1 non défini (`0/0`) | Faible (déjà géré ailleurs) | Même convention que `_precision_recall_f1` existant : `None` → `0.0` dans le rapport, documenté, pas un cas nouveau |
| `slugify_title` produit un `label` qui collide avec un `label` d'un autre champ | Faible (7 champs actuels, noms distincts) | Documenté comme limite connue, pas de résolution de collision dans ce chantier — l'utilisateur revoit le CSV de sortie avant de l'appliquer |

## Points ouverts

Aucun bloquant restant — l'intent a été entièrement tranchée via
`interview-me`. Reste hors scope explicite : optimisation de l'instruction
globale fixe, du few-shot (`Exemple texte`/`exemple valeur`), recherche
jointe multi-champs, intégration DSPy en production.
