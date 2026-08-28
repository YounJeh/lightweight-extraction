# Task List : Optimisation des prompts NER (Nom/Définition) via DSPy

Plan : [tasks/plan-dspy-prompt-tuning.md](plan-dspy-prompt-tuning.md)

---

## Task 1 : promouvoir `precision_recall_f1` dans `gold_matching.py`

**Description :** Déplacer `_precision_recall_f1` (actuellement privé,
`scripts/gold_dataset_eval.py:179-188`) vers `scripts/gold_matching.py`,
renommé `precision_recall_f1` (public, même signature :
`(tp: int, fp: int, fn: int) -> tuple[float | None, float | None, float |
None]`). Mettre à jour `gold_dataset_eval.py` pour l'importer depuis
`gold_matching` au lieu de le définir localement — aucun changement de
comportement, tous les appelants existants (`_field_metrics_evaluations`)
inchangés.

**Acceptance criteria :**
- [ ] `gold_matching.precision_recall_f1(0, 0, 0)` renvoie `(None, None,
      None)` (comportement inchangé, cas 0/0)
- [ ] `gold_matching.precision_recall_f1` produit les mêmes valeurs que
      l'ancienne `_precision_recall_f1` sur les cas déjà couverts par les
      tests existants de `gold_dataset_eval.py`
- [ ] `scripts/gold_dataset_eval.py` ne définit plus `_precision_recall_f1`
      localement

**Verification :**
- [ ] Tests : `uv run pytest -m "not live" tests/test_gold_dataset_eval.py tests/test_gold_matching.py`

**Dependencies :** None

**Files likely touched :**
- `scripts/gold_matching.py`
- `scripts/gold_dataset_eval.py`
- `tests/test_gold_matching.py`

**Estimated scope :** XS (déplacement mécanique, 1-2 fichiers)

---

## Task 2 : `scripts/dspy_markdown_cache.py` — cache disque par `source_file`

**Description :** Nouveau module pur. Fonction `get_markdown(source_file:
str, pdf_bytes: bytes, *, pdf_extractor: Any, cache_dir: Path =
CACHE_DIR) -> str` (`CACHE_DIR = Path(__file__).resolve().parent /
"_dspy_markdown_cache"`, même convention que `scripts/_ocr_tuning_cache/`
dans `scripts/validate_ocr_tuning.py:123`) :
1. `cache_dir / f"{source_file}.md"` existe → lit et renvoie son contenu,
   **sans appeler `pdf_extractor`**.
2. Sinon → `pdf_extractor.extract_text(pdf_bytes)`, écrit le résultat dans
   le fichier cache (`cache_dir.mkdir(parents=True, exist_ok=True)`
   d'abord), puis le renvoie.

Ajouter `scripts/_dspy_markdown_cache/` au `.gitignore` (même bloc que
`scripts/_ocr_tuning_cache/`).

**Acceptance criteria :**
- [ ] Premier appel sur un `source_file` absent du cache : `pdf_extractor`
      appelé une fois, fichier `.md` créé dans `cache_dir`
- [ ] Deuxième appel sur le même `source_file` : `pdf_extractor` **non**
      appelé (compteur d'appels à 0 sur un faux extracteur), contenu
      identique renvoyé
- [ ] `cache_dir` inexistant au départ ne lève pas d'erreur (créé à la
      volée)

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_markdown_cache.py` — `cache_dir`
      toujours un `tmp_path` de test, jamais `scripts/_dspy_markdown_cache/`
      réel

**Dependencies :** None

**Files likely touched :**
- `scripts/dspy_markdown_cache.py` (nouveau)
- `tests/test_dspy_markdown_cache.py` (nouveau)
- `.gitignore`

**Estimated scope :** S (nouveau module simple + tests)

---

## Task 3 : `slugify_title` — dérivation du `label` depuis `Nom`

**Description :** Fonction pure `slugify_title(title: str) -> str` (dans
`scripts/dspy_prompt_tuning.py`, ou un module dédié `scripts/text_slug.py`
si ça reste plus lisible séparé) : minuscules, accents retirés
(normalisation Unicode NFKD + filtrage des diacritiques), toute séquence de
caractères non alphanumériques remplacée par `_`, `_` de tête/queue
retirés.

**Acceptance criteria :**
- [ ] `slugify_title("Numéro de devis") == "numero_devis"` (label existant,
      régression)
- [ ] `slugify_title("Pourcentage d'acompte") == "pourcentage_d_acompte"`
      ou équivalent cohérent avec le label existant `pourcentage_acompte`
      — **si le résultat diverge du label actuel pour un `title` inchangé,
      documenter l'écart dans le plan plutôt que forcer une correspondance
      exacte artificielle** (le label actuel n'est pas nécessairement un
      slug mécanique du title d'origine)
- [ ] Titre avec espaces multiples/ponctuation (`"Délai  de paiement !"`)
      ne produit pas de `_` répétés ni de `_` en tête/queue

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k slugify` (ou
      fichier de test dédié au module choisi)

**Dependencies :** None

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py` (nouveau) ou `scripts/text_slug.py`
  (nouveau)
- fichier de test correspondant (nouveau)

**Estimated scope :** XS (fonction pure isolée)

---

## Checkpoint : Phase 1
- [ ] `uv run pytest -m "not live"` passe

---

## Task 4 : `score_field_candidate` — F1 d'un champ pour un candidat

**Description :** Dans `scripts/dspy_prompt_tuning.py`. Fonction
`score_field_candidate(field_key: str, candidate_title: str,
candidate_definition: str, *, all_fields: list[Field], gold_documents:
list[dict], data_test_dir: Path, ner_extractor: Any, markdown_cache_fn:
Callable) -> FieldScore` (`FieldScore` = dataclass/pydantic avec au moins
`f1: float`, `precision: float | None`, `recall: float | None`, `tp: int`,
`fp: int`, `fn: int`) :
1. Construit la liste de `Field` à passer à `ner_extractor.extract` :
   `all_fields` avec le field `field_key` remplacé par une copie
   (`model_copy`) portant `title=candidate_title`,
   `definition=candidate_definition` — **les autres champs restent
   inchangés** (valeurs CSV actuelles, voir Architecture Decisions du
   plan : field-par-field, jamais joint).
2. Pour chaque document de `gold_documents` dont l'annotation `field_key`
   est renseignée (même filtre que `gold_dataset_eval` / `gold_matching`) :
   récupère le markdown via `markdown_cache_fn(source_file, ...)`, appelle
   `ner_extractor.extract(markdown, fields, ...)`, retrouve le résultat du
   `field_key` visé (par `field_title == candidate_title`, puisque
   `ExtractionResult.field_title` reflète le titre demandé), classifie via
   `gold_matching.classify_field`.
3. Cumule TP/FP/FN sur tous les documents, calcule le F1 via
   `gold_matching.precision_recall_f1` (Tâche 1).

**Acceptance criteria :**
- [ ] Avec un faux `ner_extractor` déterministe (map `source_file ->
      valeur extraite` fixée à la main dans le test) et 3 documents gold
      dont les valeurs attendues sont connues, `score_field_candidate`
      renvoie le TP/FP/FN et le F1 calculés à la main pour ce cas
- [ ] Les champs autres que `field_key` reçus par `ner_extractor.extract`
      ont bien leur `title`/`definition` d'origine (assertion sur les
      arguments reçus par le faux extracteur), pas la valeur candidate
- [ ] Un document dont l'annotation `field_key` est `null` est exclu du
      calcul (cohérent avec `gold_matching`/`gold_dataset_eval` existants)

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k score_field_candidate`
      — `ner_extractor` et `markdown_cache_fn` toujours des faux injectés,
      jamais le vrai `LangExtractNerExtractor` ni un vrai PDF

**Dependencies :** Task 1, Task 2

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** M (logique de scoring, plusieurs cas de test)

---

## Checkpoint : Phase 2
- [ ] `uv run pytest -m "not live"` passe ; `score_field_candidate` prouvé
      correct avec un faux extracteur avant de brancher DSPy dessus

---

## Task 5 : dépendance `dspy` + configuration du `dspy.LM`

**Description :** `uv add dspy`. Avant d'écrire du code contre l'API DSPy,
vérifier (Documentation First, même principe que
`scripts/gold_dataset_sync.py`) la forme exacte de `dspy.LM(...)` et d'un
LM factice utilisable en test sans réseau, contre la version installée
(`uv pip show dspy`, doc/README du package dans `.venv`). Fonction
`build_dspy_lm(model_id: str | None) -> dspy.LM` dans
`scripts/dspy_prompt_tuning.py`, qui réutilise le routing existant —
import direct de `app.tools.ner_langextract._is_openai_model` et
`_api_key_for` (déjà utilisées pour LangExtract) plutôt que dupliquer la
logique provider/clé.

**Acceptance criteria :**
- [ ] `build_dspy_lm("gpt-5-mini")` construit un `dspy.LM` routé OpenAI
      (assertion sur les paramètres passés, pas d'appel réseau réel)
- [ ] `build_dspy_lm("gemini-...")` (ou `None`) construit un `dspy.LM` routé
      Gemini (défaut), cohérent avec `_provider_for`

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k build_dspy_lm`
      — aucun test de ce chantier n'instancie de vrai appel LM ; un test qui
      le ferait serait marqué `@pytest.mark.live`, jamais exécuté par moi

**Dependencies :** None

**Files likely touched :**
- `pyproject.toml`, `uv.lock`
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** S (ajout dépendance + petite fonction de routing)

---

## Task 6 : `propose_candidates` — proposition de variantes via DSPy

**Description :** `dspy.Signature` (ex. `ProposeFieldPrompt`) avec en
entrée `field_type`, `current_title`, `current_definition`, et un résumé
des échecs observés au round précédent (documents où le candidat actuel
n'a pas matché le gold — texte source tronqué + valeur gold attendue,
absent au premier round). En sortie : `new_title: str`,
`new_definition: str`. Fonction `propose_candidates(field: Field, *,
failures: list[FailureExample], n: int, lm: dspy.LM) -> list[FieldCandidate]`
(`FieldCandidate` = dataclass `title: str`, `definition: str`) qui appelle
le `dspy.Predict`/`dspy.ChainOfThought` correspondant `n` fois (ou via le
paramètre de DSPy pour plusieurs complétions si disponible — à vérifier
contre l'API réelle, Tâche 5).

**Acceptance criteria :**
- [ ] Avec un LM factice DSPy (complétions fixées à l'avance, pas de
      réseau), `propose_candidates(field, failures=[], n=3, lm=...)`
      renvoie exactement 3 `FieldCandidate`, avec `title`/`definition` non
      vides
- [ ] Le prompt envoyé au LM factice contient bien `current_title`,
      `current_definition`, et le `field_type` (assertion sur l'entrée
      reçue par le faux LM)

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k propose_candidates`
      — LM factice uniquement, aucun appel réseau

**Dependencies :** Task 5

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** M (signature DSPy + intégration LM factice en test)

---

## Checkpoint : Phase 3
- [ ] `uv run pytest -m "not live"` passe ; `propose_candidates` testé sans
      appel réseau

---

## Task 7 : `optimize_field` — boucle d'optimisation

**Description :** Dans `scripts/dspy_prompt_tuning.py`. Fonction
`optimize_field(field_key: str, *, all_fields: list[Field], gold_documents:
list[dict], n_candidates: int, n_rounds: int, score_fn=score_field_candidate,
propose_fn=propose_candidates, **deps) -> FieldResult` (`FieldResult` =
`field_key`, `baseline_title/definition`, `best_title/definition`,
`best_label` (via `slugify_title`, Tâche 3), `baseline_f1`, `best_f1`) :
1. Score le candidat baseline (`title`/`definition` actuels du CSV) via
   `score_fn`.
2. Pour `n_rounds` rounds : `propose_fn` génère `n_candidates` variantes à
   partir du meilleur connu + des échecs du round précédent ; chaque
   variante est scorée via `score_fn` ; le meilleur (baseline inclus) est
   conservé comme point de départ du round suivant.
3. Renvoie le meilleur trouvé sur l'ensemble des rounds (jamais pire que la
   baseline, puisque la baseline reste candidate à chaque comparaison).

**Acceptance criteria :**
- [ ] Avec `score_fn`/`propose_fn` factices déterministes (un candidat
      "meilleur" connu à l'avance), `optimize_field` renvoie bien ce
      candidat comme `best_*`, avec `best_f1` >= `baseline_f1`
- [ ] Si aucune variante proposée ne bat la baseline, `best_title ==
      baseline_title` (jamais de régression silencieuse)
- [ ] `best_label == slugify_title(best_title)`

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k optimize_field`
      — `score_fn`/`propose_fn` toujours des faux injectés

**Dependencies :** Task 3, Task 4, Task 6

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** M (orchestration, plusieurs cas de test)

---

## Task 8 : CLI `main()` — parcours des champs + export CSV

**Description :** `argparse` : `--field` (répétable, filtre optionnel —
défaut : tous les champs de `gold_devis_fields.csv`), `--n-candidates`
(défaut raisonnable, ex. 5), `--n-rounds` (défaut, ex. 2), `--output`
(défaut `tasks/dspy-prompt-tuning-results.csv`). Charge les champs
(`load_gold_fields`, réutilisé depuis `scripts/gold_dataset_eval.py`) et
les documents gold (`_load_gold_documents`, réutilisé depuis
`scripts/gold_dataset_sync.py`), appelle `optimize_field` pour chaque champ
demandé, puis écrit un CSV **au format exact de `gold_devis_fields.csv`**
(colonnes `section,label,Nom,Définition,Type,exemple valeur,Exemple
texte,source`) avec les `best_*` de chaque champ (colonnes non concernées —
`Type`, `exemple valeur`, `Exemple texte`, `source`, `section` — recopiées
telles quelles depuis le CSV d'origine). Affiche sur stdout, par champ,
`baseline_f1 -> best_f1`. Docstring de module avec instructions d'usage
(`uv run --no-sync python scripts/dspy_prompt_tuning.py`), même convention
que `scripts/validate_ocr_tuning.py`.

**Acceptance criteria :**
- [ ] Avec `optimize_field` factice (pas de vrai run), le CSV de sortie
      généré dans `tmp_path` est reparsable tel quel par
      `app.fields_import.import_fields` sans erreur
- [ ] `--field numero_devis` ne traite que ce champ (le CSV de sortie ne
      contient que ce champ, ou les autres champs y apparaissent inchangés
      selon le choix retenu à l'implémentation — à trancher et documenter
      dans le docstring de `main()`)
- [ ] Le résumé stdout mentionne `baseline_f1` et `best_f1` pour chaque
      champ traité

**Verification :**
- [ ] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k main` —
      `optimize_field` mocké/injecté, aucun appel LLM réel, CSV de sortie
      toujours dans `tmp_path`

**Dependencies :** Task 7

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** M (CLI + sérialisation CSV)

---

## Checkpoint : Phase 4
- [ ] `uv run pytest -m "not live"` passe intégralement (tout le chantier
      reste couvert par des doubles à ce stade)

---

## Task 9 : exécution réelle de validation contre le dataset gold

**Description :** CLAUDE.md porte une exception explicite pour DSPy — le
run réel (vrais appels LLM, LangExtract et DSPy, contre
`tests/data/dataset_gold_devis.yaml`) est autorisé pour ce chantier.
Lancer `uv run --no-sync python scripts/dspy_prompt_tuning.py --field
<un_seul_champ> --n-candidates <petit> --n-rounds <petit>` (clé API réelle
requise dans l'environnement — `GOOGLE_GENERATIVE_AI_API_KEY` ou
`OPENAI_API_KEY` selon `LLM_MODEL`). Objectif : valider le pipeline
bout-en-bout (cache markdown, `score_field_candidate` sur du vrai texte
LangExtract, `propose_candidates` sur un vrai LM, export CSV), pas produire
un résultat définitif à adopter — budget volontairement réduit.

**Acceptance criteria :**
- [ ] Le run se termine sans exception
- [ ] Le CSV de sortie (`tasks/dspy-prompt-tuning-results.csv` ou chemin
      `--output` choisi) est généré, reparsable par `import_fields`
- [ ] `baseline_f1`/`best_f1` affichés sur stdout sont des nombres
      plausibles entre 0 et 1 (pas de `NaN`, pas de valeur qui trahit un bug
      de calcul — ex. F1 > 1)
- [ ] Le cache markdown (`scripts/_dspy_markdown_cache/`) contient bien un
      fichier par document gold utilisé, réutilisé si le script est relancé
      une seconde fois (vérifiable par le temps d'exécution nettement plus
      court au 2e run)

**Verification :**
- [ ] Exécution manuelle du script (pas un test `pytest` — run réel,
      volontairement hors suite automatisée)

**Dependencies :** Task 8

**Files likely touched :**
- Aucun fichier de code (run de validation) — génère
  `tasks/dspy-prompt-tuning-results.csv` et peuple
  `scripts/_dspy_markdown_cache/`

**Estimated scope :** XS (pas de code, exécution + lecture des résultats)

---

## Checkpoint final
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Tâche 9 exécutée avec succès
- [ ] Revue avec l'utilisateur
- [ ] Proposer `/code-review-and-quality` puis une PR une fois la branche
      complète (convention CLAUDE.md)
