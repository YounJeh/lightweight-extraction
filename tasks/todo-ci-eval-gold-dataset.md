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

## Task 3: `scripts/gold_dataset_sync.py`

**Description:** Vérifier d'abord l'API exacte du SDK Langfuse pour
créer/upserter des items de Dataset (nom de la méthode, gestion d'un id
stable pour l'upsert — skill `langfuse`, ne pas deviner). Écrire
`scripts/gold_dataset_sync.py` : charge
`tests/data/dataset_gold_devis.yaml`, crée le Dataset `gold-devis` s'il
n'existe pas, puis upsert un item par `document_id` (input = `source_file` +
liste des champs à extraire ; expected_output = `annotations` ; metadata =
`human_validation` + `evidence.page` par champ).

**Acceptance criteria:**
- [ ] Exécuter le script deux fois de suite est idempotent (14 items au
      total après la 2e exécution, pas 28)
- [ ] Modifier une valeur dans le YAML puis relancer le script met à jour
      l'item correspondant côté Langfuse (pas un nouvel item)
- [ ] Le script fonctionne sans accès réseau à Gemini (aucun appel LLM ici,
      seulement l'API Langfuse)

**Verification:**
- [ ] Manuel : `uv run python scripts/gold_dataset_sync.py` (deux fois) +
      vérification dans l'UI Langfuse ou via `langfuse-cli api dataset-items
      list --dataset-name gold-devis`
- [ ] Tests: `uv run pytest -v -m "not live"` passe (le script lui-même
      n'a pas forcément de test automatisé s'il ne fait qu'orchestrer des
      appels SDK déjà couverts par ailleurs — à évaluer à l'implémentation)

**Dependencies:** Task 0

**Files likely touched:**
- `scripts/gold_dataset_sync.py`

**Estimated scope:** M (API externe à vérifier avant de coder)

---

## Task 4: `scripts/gold_dataset_eval.py` — task callable + `run_experiment` sans évaluateurs

**Description:** Écrire le `task` passé à `dataset.run_experiment(...)` :
pour chaque item, lit le PDF correspondant dans `data_test/`, appelle
`PyMuPDF4LlmTextExtractor().extract_text(pdf_bytes)` puis
`LangExtractNerExtractor().extract(text, fields, source_filename=...)` (avec
les `Field` seedés en Task 2), retourne les `ExtractionResult`. Câble
`dataset.run_experiment(name=..., task=task)` sans évaluateur pour l'instant
— objectif de cette tâche : confirmer que le pipeline réel tourne
correctement sur chaque item et produit un Dataset Run visible, avant
d'ajouter la couche de scoring.

**Acceptance criteria:**
- [ ] Exécuter le script produit un Dataset Run Langfuse avec 14 traces
      (une par document), chacune montrant `pdf_extraction` + `ner_extraction`
      imbriqués (même structure que l'app en production)
- [ ] Un échec sur un document (PDF illisible, erreur LLM) n'interrompt pas
      les 13 autres — erreurs capturées et reportées, pas de crash global

**Verification:**
- [ ] Manuel : `uv run python scripts/gold_dataset_eval.py` + vérification
      du Dataset Run dans l'UI Langfuse (14 traces liées au run)

**Dependencies:** Task 1, Task 2, Task 3

**Files likely touched:**
- `scripts/gold_dataset_eval.py`

**Estimated scope:** M (3-5 fichiers si le seeding de Task 2 est finalisé ici)

---

## Checkpoint: Pipeline branché (après Tasks 3-4)
- [ ] `scripts/gold_dataset_sync.py` : Dataset `gold-devis` avec 14 items
- [ ] `scripts/gold_dataset_eval.py` : Dataset Run visible dans l'UI Langfuse
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 5: Évaluateurs item-level (`scripts/gold_matching.py`)

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

**Acceptance criteria:**
- [ ] Cas nominal : valeur extraite == valeur gold (après normalisation) → TP
- [ ] Gold `null`, valeur extraite non vide → FP seul
- [ ] Gold non vide, rien extrait → FN seul
- [ ] Gold `null`, rien extrait → TN, exclu du calcul P/R
- [ ] Valeur extraite différente de la valeur gold → 1 FP + 1 FN
- [ ] `pourcentage_acompte` gold `30`, valeur extraite `"30 %"` (ou
      équivalent) → match (tolérance numérique)

**Verification:**
- [ ] Tests: `uv run pytest -v tests/test_gold_matching.py` — tous les cas
      ci-dessus couverts, hors réseau

**Dependencies:** Task 4

**Files likely touched:**
- `scripts/gold_matching.py`
- `scripts/gold_dataset_eval.py` *(branchement de l'évaluateur)*
- `tests/test_gold_matching.py`

**Estimated scope:** M (logique de matching + tests, 2-3 fichiers)

---

## Task 6: Évaluateurs run-level (agrégats, bucket `human_validation`)

**Description:** Évaluateur run-level agrégeant les `Evaluation` item-level
en scores globaux : P/R/F1 macro (moyenne inter-champs) et micro (agrégée),
exact-match accuracy globale, coût total/moyen, latence p50/p95, split
OCR/non-OCR (via la dimension `pages_ocr` déjà tracée). Les documents
`human_validation: false` sont exclus du calcul "principal" mais comptés à
part (nombre de documents exclus + leur score indicatif) — implémentation
exacte (deux jeux de scores calculés dans le même évaluateur vs deux Datasets
séparés) tranchée ici selon ce que permet l'API `run_experiment` vérifiée à
Task 3-4.

**Acceptance criteria:**
- [ ] Les scores run-level apparaissent sur le Dataset Run dans l'UI Langfuse
- [ ] Le score P/R/F1 "principal" ne prend en compte que les documents
      `human_validation: true`
- [ ] Un score/comptage séparé existe pour les documents `human_validation:
      false` (actuellement 0 sur les 14, mais le mécanisme doit rester
      générique — testé avec un cas simulé où au moins un document est à
      `false`)
- [ ] Split OCR/non-OCR visible séparément dans les métriques de latence

**Verification:**
- [ ] Tests: `uv run pytest -v tests/test_gold_dataset_eval.py` — agrégation
      testée sur des résultats d'item simulés (pas de vrai run réseau)
- [ ] Manuel : un run réel confirme les scores run-level dans l'UI Langfuse

**Dependencies:** Task 5

**Files likely touched:**
- `scripts/gold_dataset_eval.py`
- `tests/test_gold_dataset_eval.py`

**Estimated scope:** M (agrégation + tests, 2 fichiers)

---

## Checkpoint: Métriques (après Tasks 5-6)
- [ ] `uv run pytest -v tests/test_gold_matching.py tests/test_gold_dataset_eval.py` passe
- [ ] Un run réel affiche les scores item-level et run-level attendus dans
      l'UI Langfuse
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 7: Workflow GitHub Actions (`workflow_dispatch`) + step summary

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

**Acceptance criteria:**
- [ ] Le workflow apparaît dans l'onglet Actions de GitHub, déclenchable
      manuellement avec un champ `llm_model` optionnel
- [ ] Un run manuel réussi affiche un résumé lisible (tableau de métriques +
      lien Langfuse) dans l'interface GitHub Actions
- [ ] Aucun secret n'apparaît en clair dans les logs du run

**Verification:**
- [ ] Manuel : déclenchement réel du workflow depuis GitHub, vérification du
      résumé et du run Langfuse correspondant

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
