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
- [x] `gold_matching.precision_recall_f1(0, 0, 0)` renvoie `(None, None,
      None)` (comportement inchangé, cas 0/0)
- [x] `gold_matching.precision_recall_f1` produit les mêmes valeurs que
      l'ancienne `_precision_recall_f1` sur les cas déjà couverts par les
      tests existants de `gold_dataset_eval.py`
- [x] `scripts/gold_dataset_eval.py` ne définit plus `_precision_recall_f1`
      localement

**Verification :**
- [x] Tests : `uv run pytest -m "not live" tests/test_gold_dataset_eval.py tests/test_gold_matching.py`

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
- [x] Premier appel sur un `source_file` absent du cache : `pdf_extractor`
      appelé une fois, fichier `.md` créé dans `cache_dir`
- [x] Deuxième appel sur le même `source_file` : `pdf_extractor` **non**
      appelé (compteur d'appels à 0 sur un faux extracteur), contenu
      identique renvoyé
- [x] `cache_dir` inexistant au départ ne lève pas d'erreur (créé à la
      volée)

**Verification :**
- [x] Tests : `uv run pytest tests/test_dspy_markdown_cache.py` — `cache_dir`
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

**Description (implémentée dans `scripts/text_slug.py`, module dédié) :**
Fonction pure `slugify_title(title: str) -> str` : accents retirés
(NFKD + filtrage des marques combinantes), minuscules, **articles/
prépositions français courants filtrés** (`de`, `du`, `des`, `la`, `le`,
`l`, `d`...) — nécessaire pour matcher les labels existants (`"Nom de la
société"` -> `nom_societe`, pas `nom_de_la_societe`), tout caractère non
alphanumérique ASCII (y compris apostrophes typographiques ’, jamais
simplement supprimées) traité comme séparateur.

**Acceptance criteria :**
- [x] `slugify_title("Numéro de devis") == "numero_devis"` (label existant,
      régression)
- [x] `slugify_title("Pourcentage d'acompte") == "pourcentage_acompte"` —
      le filtrage des stopwords (`d`) suffit à matcher exactement le label
      existant, pas besoin de l'échappatoire "écart documenté" envisagée
      initialement
- [x] Titre avec espaces multiples/ponctuation (`"Délai  de paiement !!"`)
      ne produit pas de `_` répétés ni de `_` en tête/queue
- [x] **Écart documenté (attendu, pas un bug)** :
      `slugify_title("Délai de paiement du solde") == "delai_paiement_solde"`
      alors que le label existant est `delai_paiement_solde_jours` — voir
      Architecture Decisions du plan

**Verification :**
- [x] Tests : `uv run pytest tests/test_text_slug.py -q`

**Dependencies :** None

**Files likely touched :**
- `scripts/text_slug.py` (nouveau)
- `tests/test_text_slug.py` (nouveau)

**Estimated scope :** XS (fonction pure isolée)

---

## Checkpoint : Phase 1
- [x] `uv run pytest -m "not live"` passe

---

## Task 4 : `score_field_candidate` — F1 d'un champ pour un candidat

**Description (implémentée — signature légèrement simplifiée par rapport à
la version initiale du plan) :** Dans `scripts/dspy_prompt_tuning.py`.

`build_markdown_loader(*, data_test_dir, pdf_extractor, cache_dir=...) ->
Callable[[str], str]` : ferme sur le disque/l'extracteur PDF et renvoie un
chargeur `source_file -> markdown` (lit les bytes + appelle
`dspy_markdown_cache.get_markdown`) — isole `score_field_candidate` de
`data_test_dir`/la lecture disque, testable avec un simple `lambda`.

`score_field_candidate(field_key, candidate_title, candidate_definition, *,
all_fields: list[Field], gold_documents: list[dict], ner_extractor: Any,
markdown_loader: Callable[[str], str]) -> FieldScore` (`FieldScore` =
dataclass `f1: float`, `precision: float | None`, `recall: float | None`,
`tp/fp/fn: int`) :
1. Construit la liste de `Field` à passer à `ner_extractor.extract` :
   `all_fields` avec le field `field_key` remplacé par une copie
   (`model_copy`) portant `title=candidate_title`,
   `definition=candidate_definition` — **les autres champs restent
   inchangés** (valeurs CSV actuelles, voir Architecture Decisions du
   plan : field-par-field, jamais joint).
2. Pour chaque document de `gold_documents` dont `field_key` est une clé
   présente dans `annotations` (peu importe si sa `value` est `null` —
   même comportement que `gold_dataset_eval.build_field_evaluator`, qui
   laisse `classify_field` décider TN/FP/FN à partir de la présence) :
   récupère le markdown via `markdown_loader(source_file)`, appelle
   `ner_extractor.extract(markdown, fields, ...)`, retrouve le résultat du
   `field_key` visé (par `field_title == candidate_title`, puisque
   `ExtractionResult.field_title` reflète le titre demandé), classifie via
   `gold_matching.classify_field`.
3. Cumule TP/FP/FN sur tous les documents, calcule le F1 via
   `gold_matching.precision_recall_f1` (Tâche 1).

**Acceptance criteria :**
- [x] Avec un faux `ner_extractor` déterministe (map `source_file ->
      valeur extraite` fixée à la main dans le test) et 3 documents gold
      dont les valeurs attendues sont connues, `score_field_candidate`
      renvoie le TP/FP/FN et le F1 calculés à la main pour ce cas
- [x] Les champs autres que `field_key` reçus par `ner_extractor.extract`
      ont bien leur `title`/`definition` d'origine (assertion sur les
      arguments reçus par le faux extracteur), pas la valeur candidate
- [x] Un document dont `field_key` n'est **pas une clé** de `annotations`
      est exclu du calcul (extracteur jamais appelé pour ce document) —
      un document où `field_key` est présent avec `value: null` **n'est
      pas exclu** (contribue en TN/FP selon l'extraction, cohérent avec
      `gold_dataset_eval` existant)

**Verification :**
- [x] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -q` —
      `ner_extractor` et `markdown_loader` toujours des faux injectés,
      jamais le vrai `LangExtractNerExtractor` ni un vrai PDF

**Dependencies :** Task 1, Task 2

**Files likely touched :**
- `scripts/dspy_prompt_tuning.py`
- `tests/test_dspy_prompt_tuning.py`

**Estimated scope :** M (logique de scoring, plusieurs cas de test)

---

## Checkpoint : Phase 2
- [x] `uv run pytest -m "not live"` passe ; `score_field_candidate` prouvé
      correct avec un faux extracteur avant de brancher DSPy dessus

---

## Task 5 : dépendance `dspy` + configuration du `dspy.LM`

**Description (implémentée) :** `uv add dspy` (installé : `dspy==3.3.1`,
downgrade transitif de `openai` 3.0.0 -> 2.54.0 — suite complète revérifiée
verte après coup). API DSPy réelle vérifiée avant codage (Documentation
First) : `dspy.LM(model: str, ..., **kwargs)` où `model` suit la
convention LiteLLM `"provider/model"` (ex. `"gemini/gemini-2.5-flash"`,
`"openai/gpt-5-mini"`) et `api_key` passe par `**kwargs` ; `dspy.Predict(...)`
accepte un `lm=` par appel (pas besoin de `dspy.settings.configure` global) ;
`dspy.utils.DummyLM(answers=[...])` sert de LM factice en test (utilisé
Tâche 6). Fonction `build_dspy_lm(model_id: str | None) -> dspy.LM` dans
`scripts/dspy_prompt_tuning.py`, qui réutilise le routing existant — import
direct de `app.tools.ner_langextract._is_openai_model` et `_api_key_for`.
**Contrairement à LangExtract, `model_id=None` lève une `ValueError`**
plutôt que de retomber sur un défaut : DSPy exige une chaîne de modèle
explicite et ce projet a déjà choisi de ne jamais coder un modèle Gemini
par défaut en dur (voir `specs/pdf-ner-real.md`).

**Acceptance criteria :**
- [x] `build_dspy_lm("gpt-5-mini")` construit un `dspy.LM` routé OpenAI
      (assertion sur les paramètres passés, pas d'appel réseau réel)
- [x] `build_dspy_lm("gemini-...")` construit un `dspy.LM` routé Gemini
      (défaut), cohérent avec `_provider_for`
- [x] `build_dspy_lm(None)` lève `ValueError`

**Verification :**
- [x] Tests : `uv run pytest tests/test_dspy_prompt_tuning.py -k build_dspy_lm`
      — aucun test de ce chantier n'instancie de vrai appel LM ; un test qui
      le ferait serait marqué `@pytest.mark.live`

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
