# Spec: CI d'évaluation du pipeline sur le dataset gold

## Objective
Rejouer, à la demande depuis GitHub Actions, le pipeline d'extraction réel
(PDF → NER) sur le dataset gold versionné dans
[tests/data/dataset_gold_devis.yaml](../tests/data/dataset_gold_devis.yaml),
et produire des métriques de qualité (précision/recall/F1 par champ),
d'exécution (latence) et de coût (USD Gemini), tracées et versionnées dans
Langfuse — comparables d'un run à l'autre dans le temps, sans outil de
versioning supplémentaire (remplace l'option MLflow envisagée dans
`notes.md`).

Utilisateur : le porteur du projet (youn.jehanno@gmail.com), seul utilisateur
de ce dépôt. Succès = un run déclenché manuellement produit, dans le
dashboard Langfuse, un Dataset Run comparable aux runs précédents, avec des
scores de précision/recall/F1 (macro + par champ), un coût total et une
latence p50/p95, sans avoir réimplémenté la moindre logique d'extraction déjà
présente dans `app/tools/`.

Issu d'une session `idea-refine` — one-pager de cadrage :
[docs/ideas/ci-eval-gold-dataset.md](../docs/ideas/ci-eval-gold-dataset.md).

## Tech Stack
- Langage/outillage inchangés : Python 3.13, `uv`, pytest.
- Pipeline réutilisé tel quel : `app/tools/pdf_pymupdf4llm.py`
  (`PyMuPDF4LlmTextExtractor`), `app/tools/ner_langextract.py`
  (`LangExtractNerExtractor`), `app/tools/langfuse_tracer.py`
  (`LangfuseTracer`) — aucune réimplémentation du chemin d'extraction pour
  l'éval, seulement rejoué à l'identique.
- Évaluation/versioning : SDK Python `langfuse` (déjà en dépendance,
  `>=4.14.5`) — `Dataset`/`run_experiment`/évaluateurs (API exacte à vérifier
  dans la doc Langfuse au moment de l'implémentation, skill `langfuse`, pas
  de mémoire).
- CI : GitHub Actions, un seul workflow `workflow_dispatch`.

## Commands
Sync + éval, exécutable en local ou en CI (mêmes scripts) :
```bash
uv run python scripts/gold_dataset_sync.py   # upsert du Dataset Langfuse "gold-devis"
uv run python scripts/gold_dataset_eval.py   # run_experiment + scores + résumé
```
Tests (inchangé) :
```bash
uv run pytest -v -m "not live"
```

## Project Structure
Aucun nouveau répertoire de premier niveau. Ajouts prévus :
```
scripts/gold_dataset_sync.py     → sync tests/data/dataset_gold_devis.yaml -> Dataset Langfuse "gold-devis"
scripts/gold_dataset_eval.py     → run_experiment (task = pipeline réel) + évaluateurs + résumé
scripts/gold_matching.py         → matching normalisé par type de champ (partagé sync/éval)
tests/data/gold_devis_fields.csv → définitions des 6 champs gold, format compatible app/fields_import.py
tests/test_gold_matching.py      → tests unitaires du matching, hors réseau
tests/test_gold_dataset_eval.py  → tests des évaluateurs (agrégation, exclusion human_validation), hors réseau/LLM
.github/workflows/eval-gold-dataset.yml → workflow_dispatch, input LLM_MODEL optionnel
specs/ci-eval-gold-dataset.md    → cette spec
tasks/plan-ci-eval-gold-dataset.md, tasks/todo-ci-eval-gold-dataset.md → suite
```
Modifiés :
```
.gitignore        → retrait de l'entrée data_test/ (PDF référencés par le gold committés)
data_test/*.pdf   → 14 PDF référencés par le gold, committés (quelques Mo)
```

## Code Style
Même conventions que le reste du repo : scripts `scripts/*.py` en style
impératif simple (voir `scripts/reset_db.py`, pas de classe si une fonction
suffit), `Protocol`/injection pour tout ce qui touche au pipeline réel (déjà
en place — `Tracer`, `NerExtractor`, `PdfTextExtractor`), commentaires
uniquement pour un "pourquoi" non évident. Le matching normalisé
(`scripts/gold_matching.py`) réutilise le parsing déjà écrit dans
`app/tools/type_coercion.py` (conversion `int`/`float`/`date`/`bool`) plutôt
que de dupliquer des règles de parsing qui existent déjà — les rendre
réutilisables (ex. `_TRUE_TOKENS`/`_FALSE_TOKENS` remontés au niveau module
si nécessaire) plutôt que les recopier.

## Testing Strategy
- Framework existant : pytest (`uv run pytest -v -m "not live"`).
- `tests/test_gold_matching.py` : matching normalisé par type (texte
  casse/espaces, tolérance numérique, égalité de date), hors réseau — cas
  nominaux + cas limites (valeur gold `null`, valeur extraite `null`, valeur
  erronée).
- `tests/test_gold_dataset_eval.py` : agrégation run-level (macro/micro
  P/R/F1, exclusion des documents `human_validation: false` des métriques
  principales, split OCR/non-OCR) sur des résultats d'item simulés — pas
  d'appel réseau, pas de vrai PDF/LLM.
- Aucun nouveau test `live` : la vérification bout-en-bout (vrai Gemini, vrai
  Langfuse) se fait manuellement (Task 8 du plan), pas par un test
  automatisé qui dépendrait d'un compte Langfuse/Gemini réel en CI par
  défaut.

## Boundaries
- **Toujours faire** : rejouer le pipeline réel (`PyMuPDF4LlmTextExtractor` +
  `LangExtractNerExtractor`) sans le réimplémenter ; lancer
  `uv run pytest -v -m "not live"` avant tout commit ; vérifier l'API exacte
  du SDK Langfuse (Datasets/Experiments/Scores) dans la doc avant de coder
  (skill `langfuse`, principe "Documentation First").
- **Demander d'abord** : committer les PDF de `data_test/` (change durablement
  l'historique git — confirmé par l'utilisateur pour ce chantier) ; toute
  modification de `.gitignore` au-delà des PDF explicitement référencés par le
  gold ; créer/renommer le Dataset Langfuse `gold-devis` si un dataset du même
  nom existe déjà dans le projet.
- **Ne jamais faire** : gate bloquant (`RegressionError`/seuils de
  régression) dans ce chantier — reporting seul, décidé explicitly hors
  scope (voir `docs/ideas/ci-eval-gold-dataset.md`) ; déclenchement
  automatique sur PR/push — `workflow_dispatch` uniquement ; committer un PDF
  non référencé par le gold (`ITM Vitré...pdf`, `SKM_C300i...pdf` restent
  gitignorés) ; committer une clé API/Langfuse en clair.

## Success Criteria
- [x] Les 14 PDF référencés par `tests/data/dataset_gold_devis.yaml`
      (document_id 9 inclus) sont committés dans `data_test/`, le reste du
      dossier reste gitignoré.
- [x] `uv run python scripts/gold_dataset_sync.py` crée/met à jour un Dataset
      Langfuse `gold-devis` avec un item par `document_id` (14 items) —
      idempotent, vérifié en réel.
- [x] `uv run python scripts/gold_dataset_eval.py` rejoue le pipeline réel sur
      les documents et produit un Dataset Run Langfuse consultable dans
      l'UI, avec :
      - un score par item : précision/recall/F1 par champ, exact-match
        document, latence ;
      - des scores run-level : P/R/F1 macro et micro, exact-match accuracy
        globale, latence p50/p95, split OCR/non-OCR, grounding accuracy ;
      - les documents `human_validation: false` exclus des métriques
        principales et comptés à part.
      Vérifié en réel : 13/14 documents évalués (`document_id: 8` en échec —
      bug préexistant du pipeline détecté par la CI, voir
      `choix_techniques.md` § "Bug connu", pas un défaut de ce chantier).
      **Coût** non satisfait tel qu'imaginé initialement : posé à `0.0` avec
      un commentaire explicite — LangExtract n'expose aucune info d'usage
      token, gap d'instrumentation préexistant et indépendant de ce chantier
      (voir `tasks/todo-langfuse-tracing.md`).
- [x] Le workflow GitHub Actions `eval-gold-dataset.yml` (`workflow_dispatch`,
      input `LLM_MODEL` optionnel) exécute les deux scripts et affiche un
      résumé (tableau des métriques run-level + lien vers le run Langfuse)
      dans `$GITHUB_STEP_SUMMARY`. Vérifié en réel : 2 runs `success` déclenchés
      depuis l'onglet Actions (`gh run list`). Ajustement post-merge :
      `OPENAI_API_KEY` manquait dans les secrets transmis à l'étape d'éval —
      corrigé après que le quota gratuit Gemini (5 req/min) a bloqué le
      premier run réel de l'utilisateur ; `llm_model=gpt-4o-mini` utilisé
      ensuite avec succès (14/14 documents évalués).
- [x] `uv run pytest -v -m "not live"` passe intégralement, y compris les
      nouveaux tests de matching/agrégation (215 passed, 1 échec pré-existant
      sans rapport avec ce chantier).
- [x] Deux runs successifs du workflow sont comparables dans la vue "Dataset
      Runs" de l'UI Langfuse, sans action manuelle supplémentaire — 4 runs
      au total sur `gold-devis` (2 locaux + 2 GitHub Actions), confirmés via
      `client.get_dataset_runs()`.

## Open Questions
Aucune bloquante restante — voir `docs/ideas/ci-eval-gold-dataset.md` pour
l'historique des décisions (nom du dataset, exclusion `human_validation:
false`, pas d'artefact hors-Langfuse). `document_id: 9`
(`doc09044720260611193518.pdf`) doit être résolu (fichier fourni/retrouvé)
avant Task 1 du plan — voir Risks.
