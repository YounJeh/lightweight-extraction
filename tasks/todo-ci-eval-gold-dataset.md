# Task List: CI d'évaluation du pipeline sur le dataset gold

Plan de référence : [tasks/plan-ci-eval-gold-dataset.md](plan-ci-eval-gold-dataset.md) ·
Spec : [specs/ci-eval-gold-dataset.md](../specs/ci-eval-gold-dataset.md)

---

## Task 0: Résoudre `document_id: 9` (PDF manquant) ✅

**Description:** `tests/data/dataset_gold_devis.yaml` référence
`document_id: 9` → `source_file: doc09044720260611193518.pdf`, absent de
`data_test/` (vérifié : `set(source_file du YAML) - set(os.listdir(data_test))
== {"doc09044720260611193518.pdf"}`). Décision utilisateur : fournir/retrouver
le fichier plutôt que retirer l'entrée du gold. Bloquant — aucune tâche
suivante ne doit démarrer tant que ce n'est pas résolu.

**Résolu :** l'utilisateur a ajouté `data_test/doc09044720260611193518.pdf`.

**Acceptance criteria:**
- [x] `doc09044720260611193518.pdf` (ou le fichier correct si le nom a changé
      — mettre à jour `source_file` dans le YAML en conséquence) est présent
      dans `data_test/`
- [x] Script de vérification (one-off, pas besoin de le committer) confirmant
      que les 14 `source_file` du YAML ont un fichier correspondant sur disque

**Verification:**
- [x] Manuel : re-exécuter la comparaison d'ensembles ci-dessus, résultat vide

**Dependencies:** None

**Files likely touched:**
- `data_test/doc09044720260611193518.pdf` *(ajouté)*
- `tests/data/dataset_gold_devis.yaml` *(uniquement si le nom de fichier correct diffère)*

**Estimated scope:** XS (pas de code)

---

## Checkpoint: Intégrité des données (après Task 0)
- [x] Les 14 `source_file` du YAML existent tous dans `data_test/`
- [x] Revue avec l'utilisateur avant de continuer

---

## Task 1: Committer les 14 PDF gold ✅

**Description:** Retirer l'entrée `data_test/` de `.gitignore` et committer
les 14 PDF référencés par `tests/data/dataset_gold_devis.yaml`. Les deux PDF
présents dans `data_test/` mais non référencés par le gold
(`ITM Vitré - Marché de travaux - ENTECH - lot PV.pdf`,
`SKM_C300i26022410480.pdf`) restent hors du dépôt (décision utilisateur :
committer uniquement les PDF référencés) — soit en les déplaçant hors de
`data_test/` avant de retirer l'entrée du `.gitignore`, soit via une règle de
négation ciblée si on préfère les garder au même endroit sans les committer.

**Note d'implémentation :** piège Unicode découvert en committant — le nom de
fichier `ITM Vitré...pdf` sur disque encode "é" en forme décomposée (NFD, `e`
+ U+0301) alors que la ligne `.gitignore` initiale utilisait la forme
précomposée (NFC, U+00E9) : le pattern ne matchait pas, le fichier s'est
retrouvé staged malgré l'exclusion voulue. Corrigé en remplaçant l'accent par
un glob (`Vitr* - March*`) plutôt qu'en committant le caractère exact — plus
robuste à ce genre de désaccord de normalisation.

**Acceptance criteria:**
- [x] `.gitignore` ne bloque plus les 14 PDF référencés par le gold
- [x] `git status` ne montre les 2 PDF non référencés ni comme trackés ni
      comme accidentellement committés
- [x] `git show HEAD --stat` (après commit) liste bien les 14 PDF, taille
      totale raisonnable (13 Mo, vérifié avec `du -ch`)

**Verification:**
- [x] Manuel : `git ls-files data_test/` liste exactement les 14 fichiers du
      gold, ni plus ni moins

**Dependencies:** Task 0

**Files likely touched:**
- `.gitignore`
- `data_test/*.pdf` *(14 fichiers ajoutés)*

**Estimated scope:** XS (pas de code applicatif)

---

## Task 2: Fixture `tests/data/gold_devis_fields.csv` + seeding DB jetable ✅

**Description:** Extraire de `data/app.db` (table `fields`) les 6 lignes
correspondant aux clés utilisées par le gold (`numero_devis`, `nom_societe`,
`pourcentage_acompte`, `pourcentage_solde`, `delai_paiement_solde_jours`,
`duree_validite_offre`) et les écrire dans un nouveau
`tests/data/gold_devis_fields.csv`, au format attendu par
`app/fields_import.py::REQUIRED_COLUMNS` (`section, label, Nom, Définition,
Type, exemple valeur, Exemple texte, source`) — réutilisable tel quel par
`import_fields()`. **Décision utilisateur : `DATASET GOLD.csv` (racine) est
obsolète — ne pas s'y référer ni y ajouter les 6 lignes gold, seul
`tests/data/gold_devis_fields.csv` fait foi pour ce chantier.** Écrire une
petite fonction (dans
`scripts/gold_dataset_eval.py` ou un module partagé, à trancher à
l'implémentation) qui : crée une base SQLite jetable (`tempfile`, jamais
`data/app.db`), appelle `init_db`, parse le CSV via `import_fields`, et
`FieldRepository.upsert_by_key` chaque champ pour obtenir des `Field` réels
(avec `id`) — pas de nouvelle logique de parsing de champs.

**Note d'implémentation :** environnement redécouvert cassé comme documenté
dans `choix_techniques.md` (`opencv-python` GUI réinstallé par-dessus
`opencv-python-headless` par un `uv run` sans `--no-sync` précédent) —
`libGL.so.1` manquant sur les tests OCR. Corrigé avec la séquence déjà
documentée (`uv pip uninstall opencv-python opencv-python-headless && uv pip
install opencv-python-headless`), sans rapport avec ce chantier.

**Acceptance criteria:**
- [x] `tests/data/gold_devis_fields.csv` contient exactement les 6 lignes,
      colonnes conformes à `REQUIRED_COLUMNS`, `import_fields()` les parse
      sans erreur
- [x] La fonction de seeding retourne 6 `Field` avec `id` non nul, `type`
      correspondant à ce qui est en base aujourd'hui (`text`/`int`)
- [x] Aucune écriture dans `data/app.db` (DB de dev réelle) pendant ce
      seeding — vérifié par un test qui pointe vers un `tmp_path`

**Verification:**
- [x] Tests: `tests/test_gold_dataset_eval.py` (4 tests, seeding sur DB
      jetable, hors réseau)
- [x] Tests: `uv run pytest -v -m "not live"` (184 passed, 1 échec
      pré-existant sans rapport — `test_post_fields_import_replaces_definition_on_same_key`,
      déjà documenté comme lié à `DATASET GOLD.csv` local modifié avant cette
      session, 1 deselected)

**Dependencies:** Task 0 (parallélisable avec Task 1)

**Files likely touched:**
- `tests/data/gold_devis_fields.csv`
- `scripts/gold_dataset_eval.py` *(fonction de seeding, peut être créée ici en avance de Task 4)*

**Estimated scope:** S (1-2 fichiers)

---

## Checkpoint: Fondations (après Tasks 1-2)
- [x] `git show HEAD --stat` liste bien les 14 PDF
- [x] Le seeding depuis `gold_devis_fields.csv` produit 6 `Field` valides
- [x] `uv run pytest -v -m "not live"` passe, aucune régression
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 3: `scripts/gold_dataset_sync.py` ✅

**Description:** Vérifier d'abord l'API exacte du SDK Langfuse pour
créer/upserter des items de Dataset (nom de la méthode, gestion d'un id
stable pour l'upsert — skill `langfuse`, ne pas deviner). Écrire
`scripts/gold_dataset_sync.py` : charge
`tests/data/dataset_gold_devis.yaml`, crée le Dataset `gold-devis` s'il
n'existe pas, puis upsert un item par `document_id` (input = `source_file` +
liste des champs à extraire ; expected_output = `annotations` ; metadata =
`human_validation` + `evidence.page` par champ).

**Note d'implémentation :** API vérifiée contre le SDK réel avant de coder
(lecture de `langfuse/_client/client.py`/`datasets.py` installés, plus un
test empirique en direct contre le projet Langfuse de l'utilisateur) :
`create_dataset(name=...)` idempotent par nom (deux appels → même id) ;
`create_dataset_item(id=...)` "Upserts if an item with id already exists"
(docstring SDK). Id d'item préfixé (`gold-devis-{document_id}`) car les ids
doivent être globalement uniques, pas seulement par dataset.

**Acceptance criteria:**
- [x] Exécuter le script deux fois de suite est idempotent (14 items au
      total après la 2e exécution, pas 28) — vérifié en réel via
      `langfuse-cli api dataset-items list --dataset-name gold-devis`
      (`totalItems: 14` après deux runs)
- [x] Modifier une valeur dans le YAML puis relancer le script met à jour
      l'item correspondant côté Langfuse (pas un nouvel item) — couvert par
      `tests/test_gold_dataset_sync.py::test_sync_rerun_updates_a_changed_document`
- [x] Le script fonctionne sans accès réseau à Gemini (aucun appel LLM ici,
      seulement l'API Langfuse)

**Verification:**
- [x] Manuel : `uv run python scripts/gold_dataset_sync.py` (deux fois) +
      vérification via `langfuse-cli api dataset-items list --dataset-name
      gold-devis`
- [x] Tests: `tests/test_gold_dataset_sync.py` (4 tests, client Langfuse
      factice, hors réseau) + `uv run pytest -v -m "not live"` (188 passed,
      1 échec pré-existant sans rapport, 1 deselected)

**Dependencies:** Task 0

**Files likely touched:**
- `scripts/gold_dataset_sync.py`

**Estimated scope:** M (API externe à vérifier avant de coder)

---

## Task 4: `scripts/gold_dataset_eval.py` — task callable + `run_experiment` sans évaluateurs ✅

**Description:** Écrire le `task` passé à `dataset.run_experiment(...)` :
pour chaque item, lit le PDF correspondant dans `data_test/`, appelle
`PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)` puis
`LangExtractNerExtractor().extract(text, fields, source_filename=...)` (avec
les `Field` seedés en Task 2), retourne les `ExtractionResult`. Câble
`dataset.run_experiment(name=..., task=task)` sans évaluateur pour l'instant
— objectif de cette tâche : confirmer que le pipeline réel tourne
correctement sur chaque item et produit un Dataset Run visible, avant
d'ajouter la couche de scoring.

**Note d'implémentation :** `max_concurrency=3` par défaut dans `run_eval`
(pas la valeur par défaut du SDK, 50) — OCR coûteux en CPU/mémoire par
document, pas de bénéfice à paralléliser largement 14 docs. Extracteurs
injectables (`pdf_extractor`/`ner_extractor` optionnels sur `build_task`)
pour tester le câblage hors réseau, tout en laissant les vraies classes par
défaut en usage réel.

**Acceptance criteria:**
- [x] Exécuter le script produit un Dataset Run Langfuse avec 14 traces
      (une par document), chacune montrant `pdf_extraction` + `ner_extraction`
      imbriqués (même structure que l'app en production) — vérifié en réel :
      `experiment-item-run > experiment-item-task > pdf_extraction +
      ner_extraction > extract-fields (generation)`, via l'API `observations`
- [x] Un échec sur un document (PDF illisible, erreur LLM) n'interrompt pas
      les 13 autres — comportement du SDK (`run_experiment`, "Failed items
      are handled gracefully"), pas de code custom nécessaire ; les 14
      documents du run réel se sont exécutés sans erreur

**Verification:**
- [x] Manuel : `uv run python scripts/gold_dataset_eval.py` (arrière-plan,
      ~7 min avec OCR réel) → Dataset Run
      `gold-devis-eval - 2026-08-27T13:38:47.859123Z`, 14 items confirmés via
      `client.get_dataset_run(...)` (14 `dataset_run_items`, chacun avec un
      `trace_id`)
- [x] Tests: `tests/test_gold_dataset_eval.py` (6 tests, extracteurs
      factices, hors réseau) + `uv run pytest -v -m "not live"` (190 passed,
      1 échec pré-existant sans rapport, 1 deselected)

**Dependencies:** Task 1, Task 2, Task 3

**Files likely touched:**
- `scripts/gold_dataset_eval.py`

**Estimated scope:** M (3-5 fichiers si le seeding de Task 2 est finalisé ici)

---

## Checkpoint: Pipeline branché (après Tasks 3-4)
- [x] `scripts/gold_dataset_sync.py` : Dataset `gold-devis` avec 14 items
- [x] `scripts/gold_dataset_eval.py` : Dataset Run visible dans l'UI Langfuse
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 5: Évaluateurs item-level (`scripts/gold_matching.py`) ✅

**Description:** `scripts/gold_matching.py` : fonction de matching normalisé
par type de champ (texte insensible casse/espaces ; numérique — tolérance à
définir, ex. arrondi/tokenisation du `%` ; date — comparaison via
`date.fromisoformat` après normalisation), réutilisant le parsing de
`app/tools/type_coercion.py`. Calcule, pour un document, TP/FP/FN par champ
(convention : valeur erronée = 1 FP + 1 FN, voir Architecture Decisions du
plan), l'exact-match du document, la grounding accuracy (page extraite vs
`evidence.page` gold, uniquement sur les valeurs correctes), la latence et le
coût (lus depuis les `usage_details`/`cost_details` de la trace). Câblé comme
évaluateur item-level de `run_experiment` (`Evaluation(name=..., value=...)`
par métrique).

**Note d'implémentation :** `typed_value` préféré à `value` pour la
comparaison (valeur déjà nettoyée par le pipeline, cf.
`app/tools/ner_langextract.py::_typed_value`). `human_validation` posé comme
`Evaluation` item-level (pas seulement lu depuis `item.metadata`) pour que
l'évaluateur run-level (Task 6) puisse filtrer sans requête supplémentaire.

**Acceptance criteria:**
- [x] Cas nominal : valeur extraite == valeur gold (après normalisation) → TP
- [x] Gold `null`, valeur extraite non vide → FP seul
- [x] Gold non vide, rien extrait → FN seul
- [x] Gold `null`, rien extrait → TN, exclu du calcul P/R
- [x] Valeur extraite différente de la valeur gold → 1 FP + 1 FN
- [x] `pourcentage_acompte` gold `30`, valeur extraite `"30 %"` (ou
      équivalent) → match (tolérance numérique)

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_gold_matching.py` (16 passed) +
      `tests/test_gold_dataset_eval.py` (10 tests évaluateur item-level) —
      tous les cas ci-dessus couverts, hors réseau

**Dependencies:** Task 4

**Files likely touched:**
- `scripts/gold_matching.py`
- `scripts/gold_dataset_eval.py` *(branchement de l'évaluateur)*
- `tests/test_gold_matching.py`

**Estimated scope:** M (logique de matching + tests, 2-3 fichiers)

---

## Task 6: Évaluateurs run-level (agrégats, bucket `human_validation`) ✅

**Description:** Évaluateur run-level agrégeant les `Evaluation` item-level
en scores globaux : P/R/F1 macro (moyenne inter-champs) et micro (agrégée),
exact-match accuracy globale, coût total/moyen, latence p50/p95, split
OCR/non-OCR (via la dimension `pages_ocr` déjà tracée). Les documents
`human_validation: false` sont exclus du calcul "principal" mais comptés à
part (nombre de documents exclus + leur score indicatif) — implémentation
exacte (deux jeux de scores calculés dans le même évaluateur vs deux Datasets
séparés) tranchée ici selon ce que permet l'API `run_experiment` vérifiée à
Task 3-4.

**Note d'implémentation — coût non mesurable :** `cost_usd_total` posé à
`0.0` avec un commentaire explicite plutôt qu'omis. Découverte en
implémentant : LangExtract n'expose aucune info d'usage token dans son objet
de retour, donc `trace_llm_call` (`app/tools/langfuse_tracer.py`) ne pose
jamais `usage_details`/`cost_details` sur ses generations — gap déjà
documenté (`tasks/todo-langfuse-tracing.md`, Task 6 post-launch), confirmé
indépendant de ce chantier. Nécessiterait d'instrumenter LangExtract plus
profondément (hors scope).

**Découverte du run réel — bug pipeline préexistant, pas de ce chantier :**
`document_id: 8` (`104__DEVIS_25110230_VERSION_A03.pdf`, déjà connu pour ses
soucis d'OCR, voir `choix_techniques.md`) échoue avec `ValueError: Source
tokens and extraction tokens cannot be empty.` pendant l'arbitrage LLM
(`arbitrate-conflict-Pourcentage d'acompte`, logique de dédup décrite dans
`choix_techniques.md`). Bug latent dans `app/tools/ner_langextract.py`, hors
scope de ce chantier (non traité ici) — mais la CI l'a détecté exactement
comme prévu : `run_experiment` a géré l'échec sans interrompre les 13 autres
documents (comportement du SDK, voir Task 4), et `documents_evaluated: 13`
reflète fidèlement l'exclusion. Ce document reste dans le Dataset Langfuse
(sync inchangée) et réapparaîtra dans un futur run une fois le bug corrigé.

**Acceptance criteria:**
- [x] Les scores run-level apparaissent sur le Dataset Run dans l'UI Langfuse
- [x] Le score P/R/F1 "principal" ne prend en compte que les documents
      `human_validation: true`
- [x] Un score/comptage séparé existe pour les documents `human_validation:
      false` (actuellement 0 sur les 14, mais le mécanisme reste générique —
      testé avec un cas simulé où au moins un document est à `false`,
      `test_run_evaluator_excludes_unvalidated_documents_from_main_metrics`)
- [x] Split OCR/non-OCR visible séparément dans les métriques de latence

**Verification:**
- [x] Tests: `tests/test_gold_dataset_eval.py` (5 tests dédiés à
      l'agrégation run-level, résultats d'item simulés, hors réseau) +
      `uv run pytest -v -m "not live"` (215 passed, 1 échec pré-existant
      sans rapport, 1 deselected)
- [x] Manuel : run réel confirmé — `documents_evaluated: 13`,
      `f1_macro: 0.478`, `precision_micro: 0.429`, `recall_micro: 0.625`,
      `exact_match_accuracy: 0.077`, `grounding_accuracy: 0.931` (27/29),
      `latency_p50_seconds: 21.6`, `latency_p95_seconds: 60.8`,
      `documents_with_ocr: 12`, `documents_without_ocr: 1`,
      `cost_usd_total: 0.0` (commentée) — Dataset Run :
      https://cloud.langfuse.com/project/cmt1cflz104nvad0g35njubp0/datasets/cmtbkest500w5ad0fuzsrgoqr/runs/fa33d487-54f7-4301-9473-b9b66b8ac34b

**Dependencies:** Task 5

**Files likely touched:**
- `scripts/gold_dataset_eval.py`
- `tests/test_gold_dataset_eval.py`

**Estimated scope:** M (agrégation + tests, 2 fichiers)

---

## Checkpoint: Métriques (après Tasks 5-6)
- [x] `uv run pytest -v tests/test_gold_matching.py tests/test_gold_dataset_eval.py` passe
- [x] Un run réel affiche les scores item-level et run-level attendus dans
      l'UI Langfuse
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 7: Workflow GitHub Actions (`workflow_dispatch`) + step summary ✅ (code) — déclenchement réel en attente

**Description:** `.github/workflows/eval-gold-dataset.yml` : déclenché en
`workflow_dispatch` uniquement, avec un input optionnel `llm_model` (mappé
sur la variable d'environnement `LLM_MODEL`, pour comparer des modèles sans
changer de code). Étapes : checkout, setup `uv`, `uv sync`,
`uv run python scripts/gold_dataset_sync.py`,
`uv run python scripts/gold_dataset_eval.py`, puis écriture d'un résumé
(tableau des métriques run-level + lien vers le Dataset Run Langfuse) dans
`$GITHUB_STEP_SUMMARY`. Secrets : `GOOGLE_GENERATIVE_AI_API_KEY`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (mêmes noms que les secrets
Cloud Run existants — à créer comme secrets de repo GitHub, distincts de
Secret Manager).

**Note d'implémentation :** `gh secret list`/`gh secret set` renvoient `403
Resource not accessible by integration` avec le token disponible dans cet
environnement (`GITHUB_TOKEN` d'app, pas un PAT classique) — impossible de
créer les secrets de repo depuis ici, malgré des droits `admin:true` sur le
repo par ailleurs (limitation connue des tokens d'app GitHub sur la gestion
des secrets Actions). L'utilisateur doit créer les 4 secrets lui-même (voir
commandes dans la Checklist finale). Mêmes commandes `opencv-python-headless`
que le `Dockerfile` de déploiement (`choix_techniques.md`) — même incident
déjà rencontré deux fois dans ce repo (dev local, Cloud Run), anticipé ici
plutôt que découvert à l'usage.

**Acceptance criteria:**
- [x] Le workflow apparaît dans l'onglet Actions de GitHub, déclenchable
      manuellement avec un champ `llm_model` optionnel — YAML validé
      localement (`python3 -c "import yaml; yaml.safe_load(...)"`), visible
      dans Actions dès que la branche est poussée sur GitHub
- [ ] Un run manuel réussi affiche un résumé lisible (tableau de métriques +
      lien Langfuse) dans l'interface GitHub Actions — **en attente** : push
      de la branche + secrets de repo à créer par l'utilisateur, puis
      déclenchement réel (voir Task 8)
- [x] Aucun secret n'apparaît en clair dans les logs du run — tous passés
      via `secrets.*`/`env:`, jamais en argument de commande visible

**Verification:**
- [ ] Manuel : déclenchement réel du workflow depuis GitHub, vérification du
      résumé et du run Langfuse correspondant — **en attente**, voir Task 8

**Dependencies:** Task 6

**Files likely touched:**
- `.github/workflows/eval-gold-dataset.yml`

**Estimated scope:** S (1 fichier, mais nécessite les secrets de repo configurés)

---

## Task 8: Vérification manuelle bout-en-bout + housekeeping

**Description:** Déclencher le workflow réel une fois (voir Task 7),
confirmer que le Dataset Run est comparable à un run précédent dans la vue
"Dataset Runs" de l'UI Langfuse. Mettre à jour `README.md` (comment
déclencher l'éval, où consulter les résultats) et cocher les success criteria
de `specs/ci-eval-gold-dataset.md`. Évaluer si `choix_techniques.md` doit
être mis à jour (CLAUDE.md : uniquement ce qui touche au cœur de
l'application — cette CI est de l'outillage, probablement hors scope de ce
fichier, à confirmer plutôt que deviner).

**Acceptance criteria:**
- [ ] Deux runs successifs du workflow sont comparables dans l'UI Langfuse
      sans action manuelle supplémentaire
- [ ] `README.md` documente le déclenchement de l'éval et où consulter les
      résultats
- [ ] Tous les success criteria de `specs/ci-eval-gold-dataset.md` sont
      cochés ou explicitement justifiés

**Verification:**
- [ ] Manuel : relecture croisée `specs/ci-eval-gold-dataset.md` § Success
      Criteria vs état réel
- [ ] Tests: `uv run pytest -v -m "not live"` passe intégralement

**Dependencies:** Task 7

**Files likely touched:**
- `README.md`
- `specs/ci-eval-gold-dataset.md` *(cocher les success criteria)*

**Estimated scope:** XS

---

## Checkpoint: Complete (après Task 8)
- [ ] Tous les success criteria de `specs/ci-eval-gold-dataset.md` sont cochés
- [ ] Deux runs successifs du workflow sont comparables dans l'UI Langfuse
- [ ] Revue finale avec l'utilisateur
