# Task List: Mock UI — Field Management & PDF Extraction

Plan de référence : [tasks/plan.md](plan.md) · Spec : [specs/mock-ui.md](../specs/mock-ui.md)

---

## Task 1: Scaffolding du projet et app FastHTML démarrable

**Description:** Initialiser le projet avec `uv`, déclarer les dépendances de la
stack (FastHTML, Pydantic, pytest, + `python-multipart` si nécessaire pour
l'upload — à vérifier), créer le squelette de dossiers (`app/`, `tests/`,
`data/`) et une app FastHTML minimale qui démarre et répond sur une route de
base.

**Acceptance criteria:**
- [x] `uv sync` installe l'environnement sans erreur
- [x] `uv run python -m app.main` démarre un serveur FastHTML local sans erreur
- [x] `.gitignore` exclut `data/*.db` (règle globale `*.db`), `__pycache__`, `.venv`

**Verification:**
- [x] Tests: `uv run pytest -v` (test de fumée `tests/test_app.py`)
- [x] Build: `uv sync` réussit
- [x] Manuel: `curl http://localhost:5001/` → HTTP 200 pendant que le serveur tourne

**Dependencies:** None

**Files likely touched:**
- `pyproject.toml`
- `app/__init__.py`
- `app/main.py`
- `.gitignore`
- `data/.gitkeep`

**Estimated scope:** S (1-2 fichiers de code + config)

---

## Task 2: Schéma SQLite, modèles Pydantic et fixture de test DB

**Description:** Définir le schéma SQLite (tables `fields`, `extraction_runs`,
`extraction_results`) dans `app/db.py` (création via `CREATE TABLE IF NOT
EXISTS`), les modèles Pydantic correspondants dans `app/models.py`
(`Field`, `FieldCreate`, `FieldUpdate`, `ExtractionRun`, `ExtractionResult`), et
une fixture pytest (`tests/conftest.py`) qui fournit une base SQLite temporaire
isolée par test.

**Acceptance criteria:**
- [x] Le schéma crée les 3 tables sans erreur sur une base vide
- [x] Les modèles Pydantic couvrent tous les champs listés dans la spec
  (`specs/mock-ui.md`, section Code Style)
- [x] La fixture de test ne touche jamais le fichier SQLite de dev (`data/app.db`)
  — `db_conn` utilise `tmp_path`, vérifié par un test dédié

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_db.py` vérifie la création du schéma
  (+ idempotence + isolation de la fixture)
- [x] Manuel: inspection de `data/app.db` après lancement de l'app — tables
  `fields`, `extraction_runs`, `extraction_results` présentes

**Dependencies:** Task 1

**Files likely touched:**
- `app/db.py`
- `app/models.py`
- `tests/conftest.py`
- `tests/test_db.py`

**Estimated scope:** M (3-4 fichiers)

---

## Checkpoint: Foundation (après Tasks 1-2)
- [ ] `uv run python -m app.main` démarre sans erreur
- [ ] `uv run pytest` passe
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 3: `FieldRepository` (CRUD) + tests unitaires

**Description:** Implémenter la couche de persistance des champs
(`app/repository.py` : `create`, `list_all`, `get`, `update`, `delete`) au-dessus
de `app/db.py`, avec requêtes SQL paramétrées uniquement.

**Acceptance criteria:**
- [x] Chaque méthode CRUD fonctionne indépendamment et persiste réellement en DB
- [x] Une erreur de validation (titre vide) est rejetée avant écriture (create et update)
- [x] Aucune concaténation de chaîne dans le SQL (requêtes paramétrées `?`)

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_field_repository.py` (7/7 passent)
- [x] Manuel: couvert par les tests `test_create_and_get` / `test_delete_removes_field`

**Dependencies:** Task 2

**Files likely touched:**
- `app/repository.py`
- `tests/test_field_repository.py`

**Estimated scope:** S (1-2 fichiers)

---

## Task 4: Page et routes "Champs" (slice verticale 1)

**Description:** Construire la page listant tous les champs (titre, définition,
exemples) avec formulaire de création et actions update/delete, câblée sur
`FieldRepository`. Inclut le layout de base avec barre latérale (même minimale
à ce stade, complétée en Task 8).

**Acceptance criteria:**
- [x] Un champ créé via le formulaire apparaît immédiatement dans la liste
- [x] Update et delete fonctionnent depuis l'UI sans rechargement manuel de l'URL
  (POST + redirect 303 vers `/fields`)
- [x] Un champ créé reste visible après redémarrage du serveur (persistance réelle)

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_fields_routes.py` (5/5 passent)
- [x] Manuel: parcours complet create → list → update → delete vérifié via curl
  contre le serveur réel (`uv run python -m app.main`), y compris redémarrage

**Dependencies:** Task 3

**Files likely touched:**
- `app/routes/fields.py`
- `app/ui/layout.py`
- `app/ui/components.py`
- `tests/test_fields_routes.py`

**Estimated scope:** M (3-4 fichiers)

---

## Checkpoint: Champs (après Tasks 3-4)
- [ ] Créer/lister/modifier/supprimer un champ fonctionne de bout en bout dans le navigateur
- [ ] Un champ créé survit à un redémarrage du serveur
- [ ] `uv run pytest` passe
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 5: Interfaces `Protocol` + outils mock (PDF/NER) + tests unitaires

**Description:** Définir `PdfTextExtractor` et `NerExtractor` comme `Protocol`
dans `app/tools/__init__.py`, puis implémenter `MockPdfTextExtractor` (texte
factice fixe, indépendant du contenu réel du PDF) et `MockNerExtractor`
(valeur factice déterministe par champ coché, sans grounding réel), chacun
marquant ses résultats comme `source="mock"`.

**Acceptance criteria:**
- [x] `MockPdfTextExtractor.extract_text` retourne toujours le même texte,
  quel que soit le contenu du fichier passé
- [x] `MockNerExtractor.extract` retourne un `ExtractionResult` par champ
  passé en entrée, avec `source="mock"`
- [x] Les deux mocks sont déterministes (mêmes entrées → mêmes sorties)

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_mock_tools.py` (5/5 passent)

**Dependencies:** Task 2 (dépend des modèles `Field`/`ExtractionResult`, pas des repositories — parallélisable avec Task 3/4)

**Files likely touched:**
- `app/tools/__init__.py`
- `app/tools/mock_pdf.py`
- `app/tools/mock_ner.py`
- `tests/test_mock_tools.py`

**Estimated scope:** S (2-3 fichiers)

---

## Task 6: `ExtractionRunRepository` (persistance des runs) + tests unitaires

**Description:** Implémenter la persistance des runs d'extraction
(`app/extraction_repository.py` : `create_run`, `list_runs`, `get_run`), stockant
le nom du document (métadonnée uniquement) et la liste des `ExtractionResult`
associés.

**Acceptance criteria:**
- [x] Un run créé (nom de document + résultats) est relisible via `get_run`/`list_runs`
- [x] Aucune donnée binaire du PDF n'est écrite en DB — uniquement le nom du document
  (`create_run(document_name: str, ...)`, jamais de `bytes`)
- [x] Requêtes SQL paramétrées uniquement

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_extraction_repository.py` (5/5 passent)

**Dependencies:** Task 2

**Files likely touched:**
- `app/extraction_repository.py`
- `tests/test_extraction_repository.py`

**Estimated scope:** S (1-2 fichiers)

---

## Task 7: Page et routes "Extraction" (slice verticale 2)

**Description:** Construire la page d'upload PDF avec liste de cases à cocher
des champs disponibles (issus de `FieldRepository`), déclenchant à la
soumission : extraction de texte mockée → NER mocké → persistance du run via
`ExtractionRunRepository` → affichage des résultats avec badge "mock". Le
fichier PDF lui-même n'est jamais écrit sur disque ou en DB au-delà de la durée
de la requête.

**Acceptance criteria:**
- [x] L'utilisateur peut uploader un PDF, cocher un sous-ensemble de champs, et lancer l'extraction
- [x] Le résultat affiché contient une valeur simulée par champ coché, marquée comme mock
- [x] Le run est persisté et reste consultable après redémarrage du serveur
  (`GET /extraction/runs/{id}`, liste des runs sur `/extraction`)
- [x] Aucune trace durable du fichier PDF source (disque ou DB) après la requête
  — seul `pdf.filename` est stocké, vérifié par un test dédié sur le schéma DB

**Verification:**
- [x] Tests: `uv run pytest -v tests/test_extraction_routes.py` (7/7 passent)
- [x] Manuel: upload d'un PDF factice via curl contre le serveur réel, vérifié
  redirection vers `/extraction/runs/1`, badge "mock", valeur issue de
  l'exemple du champ, et nom du document affiché

**Dependencies:** Task 4 (liste des champs disponibles), Task 5 (outils mock), Task 6 (persistance des runs)

**Files likely touched:**
- `app/routes/extraction.py`
- `app/ui/components.py`
- `tests/test_extraction_routes.py`

**Estimated scope:** M (3 fichiers)

---

## Checkpoint: Extraction (après Tasks 5-7)
- [x] Parcours upload → sélection champs → extraction simulée fonctionne de bout en bout (vérifié via curl contre le serveur réel)
- [x] Le run d'extraction persiste et reste consultable après redémarrage
- [x] Le fichier PDF source n'est jamais conservé durablement
- [x] `uv run pytest` passe (33/33)
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 8: Navigation partagée, états vides et erreurs

**Description:** Finaliser la barre latérale commune (liens vers "Champs" et
"Extraction"), gérer les états vides (aucun champ créé → message + lien vers la
création ; aucun run d'extraction → message adapté) et les erreurs de
validation (titre vide, fichier non-PDF) avec un retour visible à l'utilisateur.

**Acceptance criteria:**
- [ ] Navigation entre les deux pages fonctionne depuis n'importe quelle page
- [ ] Un état sans champ n'empêche pas d'accéder à la page Extraction (juste aucune case à cocher, avec message clair)
- [ ] Une erreur de validation s'affiche dans l'UI sans crash serveur (500)

**Verification:**
- [ ] Tests: `uv run pytest -v` (cas d'erreur ajoutés aux suites de routes existantes)
- [ ] Manuel: navigation croisée + tentative de soumission invalide sur les deux pages

**Dependencies:** Task 4, Task 7

**Files likely touched:**
- `app/ui/layout.py`
- `app/routes/fields.py`
- `app/routes/extraction.py`

**Estimated scope:** S (2-3 fichiers)

---

## Task 9: Housekeeping (README, `.gitignore`, revue finale)

**Description:** Documenter les commandes d'installation/lancement/tests dans
le `README.md`, vérifier que `.gitignore` couvre bien tous les artefacts
runtime (`data/*.db`, `__pycache__`, `.venv`), et repasser explicitement chaque
critère de succès de `specs/mock-ui.md` pour cocher ce qui est fait.

**Acceptance criteria:**
- [ ] `README.md` contient les commandes `uv sync` / `uv run python -m app.main` / `uv run pytest`
- [ ] `.gitignore` vérifié complet
- [ ] Tous les critères de succès de la spec sont cochés ou justifiés s'ils ne le sont pas

**Verification:**
- [ ] Tests: `uv run pytest -v` (suite complète, aucune régression)
- [ ] Manuel: relecture croisée `specs/mock-ui.md` § Success Criteria vs état réel de l'app

**Dependencies:** Task 8

**Files likely touched:**
- `README.md`
- `.gitignore`
- `specs/mock-ui.md` (cocher les critères de succès)

**Estimated scope:** XS (2-3 fichiers, pas de nouveau code applicatif)

---

## Checkpoint: Complete (après Task 9)
- [ ] Tous les critères de succès de `specs/mock-ui.md` sont cochés
- [ ] `uv run pytest` passe intégralement
- [ ] Parcours manuel complet (champs → extraction) validé dans le navigateur
- [ ] Revue finale avec l'utilisateur
