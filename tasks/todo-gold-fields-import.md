# Task List : Import du dataset gold vers les champs

Plan : [tasks/plan-gold-fields-import.md](plan-gold-fields-import.md) ·
Idée : [docs/ideas/gold-fields-import.md](../docs/ideas/gold-fields-import.md)

---

## Task 1 : `FieldExample` + `Field.key`/`Field.section` + migration

**Description :** Ajouter `class FieldExample(BaseModel): context: str;
value: str | None = None; source: str | None = None` dans `app/models.py`.
Sur `FieldBase` : ajouter `key: str`, `section: str | None = None`, et
changer `examples: list[str]` en `examples: list[FieldExample]`. Dans
`app/db.py` : ajouter `key TEXT NOT NULL DEFAULT ''` et `section TEXT` à la
définition `CREATE TABLE fields`, ajouter les deux
`_add_column_if_missing(...)` correspondants dans `init_db` (schéma
pré-migration), et ajouter `conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS
idx_fields_key ON fields(key)")` (fonctionne aussi bien sur une table neuve
que migrée, idempotent).

**Acceptance criteria :**
- [x] `FieldCreate(title=..., definition=...)` sans `key` lève une
      `ValidationError`
- [x] `Field(key="k1", ..., examples=[{"context": "texte", "value": "10",
      "source": "doc.pdf"}])` parse `examples[0]` en `FieldExample` typé
- [x] `init_db()` sur une DB neuve crée `fields.key`/`fields.section` et
      l'index unique directement
- [x] `init_db()` sur une DB dont `fields` existe déjà sans `key`/`section`
      (schéma pré-migration) ajoute les colonnes et l'index sans erreur ni
      perte de données ; un second appel reste sans effet (idempotent)

**Verification :**
- [x] Tests : `uv run pytest tests/test_models.py tests/test_db.py`

**Dependencies :** None

**Files likely touched :**
- `app/models.py`
- `app/db.py`
- `tests/test_models.py`
- `tests/test_db.py`

**Estimated scope :** S (4 fichiers)

---

## Task 2 : `FieldRepository` — CRUD adapté + `upsert_by_key`

**Description :** Étendre `create`/`update`/`_row_to_field`
(app/repository.py) pour lire/écrire `key`, `section`, et sérialiser/
désérialiser `examples` comme une liste de `FieldExample` (JSON de dicts, pas
de strings). Ajouter `_require_key` (même forme que `_require_title` :
`strip()`, lève `ValueError` si vide). Attraper `sqlite3.IntegrityError` sur
`create`/`update` et le relever en `ValueError("key already exists")` pour
rester cohérent avec la gestion d'erreur déjà en place dans
`app/routes/fields.py` (`except ValueError`). Ajouter
`upsert_by_key(data: FieldCreate) -> Field` via
`INSERT INTO fields (...) VALUES (...) ON CONFLICT(key) DO UPDATE SET
title=excluded.title, definition=excluded.definition, section=excluded.section,
examples=excluded.examples, type=excluded.type` — remplacement complet, pas
de fusion. Mettre à jour tous les appels `FieldCreate(...)`/`FieldUpdate(...)`
existants dans les tests (ajout de `key=...`, `examples` enveloppés en
`FieldExample`).

**Acceptance criteria :**
- [x] `repo.create(FieldCreate(key="k1", ...))` puis `repo.get(id)` renvoie
      `key`/`section`/`examples` correctement typés
- [x] `repo.create(FieldCreate(key="  ", ...))` lève `ValueError`
- [x] Créer deux champs avec le même `key` lève `ValueError` (pas une
      `sqlite3.IntegrityError` brute)
- [x] `repo.upsert_by_key(FieldCreate(key="k1", ...))` crée un nouveau champ
      si `k1` n'existe pas encore
- [x] `repo.upsert_by_key(FieldCreate(key="k1", title="Nouveau titre", ...))`
      remplace entièrement le champ existant (title/definition/type/section/
      examples) si `k1` existe déjà — l'`id` ne change pas

**Verification :**
- [x] Tests : `uv run pytest tests/test_field_repository.py
      tests/test_fields_routes.py tests/test_extraction_routes.py`

**Dependencies :** Task 1

**Files likely touched :**
- `app/repository.py`
- `tests/test_field_repository.py`
- `tests/test_fields_routes.py`
- `tests/test_extraction_routes.py`

**Estimated scope :** M (4 fichiers, dont 3 mécaniques)

---

## Checkpoint : Phase 1a — Modèle + persistance
- [x] `uv run pytest -m "not live" tests/test_models.py tests/test_db.py
      tests/test_field_repository.py tests/test_fields_routes.py
      tests/test_extraction_routes.py` passe

---

## Task 3 : Compat NER réel — `ner_langextract.py`

**Description :** Adapter `_example_attributes`/`_build_example`
(app/tools/ner_langextract.py) pour lire `field.examples[0].context` au lieu
de `field.examples[0]` (string brute). Aucune autre logique ne change :
`_typed_hint` garde sa signature `(example: str, field_type: FieldType)`,
seul l'appelant change ce qu'il lui passe. Mettre à jour les Field(...) des
tests concernés avec `key=...` et `examples=[FieldExample(context=...)]`.

**Acceptance criteria :**
- [x] `test_typed_hint_narrows_example_to_typed_substring` et les autres cas
      de `test_ner_langextract_typed_hint.py` passent inchangés dans leur
      intention (mêmes hints extraits, juste la construction du `Field`
      change)
- [x] `test_ner_langextract_dedupe.py` passe avec les `Field(...)` mis à jour
      (`key` ajouté, `examples=[]` reste valide tel quel)
- [x] `test_ner_langextract_live.py` (marqué `live`, skip sans clé API) mis à
      jour de la même façon, pour rester cohérent si lancé avec une clé

**Verification :**
- [x] Tests : `uv run pytest -m "not live" tests/test_ner_langextract_typed_hint.py
      tests/test_ner_langextract_dedupe.py`

**Dependencies :** Task 1

**Files likely touched :**
- `app/tools/ner_langextract.py`
- `tests/test_ner_langextract_typed_hint.py`
- `tests/test_ner_langextract_dedupe.py`
- `tests/test_ner_langextract_live.py`

**Estimated scope :** M (4 fichiers)

---

## Task 4 : Compat NER mock — `mock_ner.py`

**Description :** Adapter `MockNerExtractor._mock_result`
(app/tools/mock_ner.py) pour lire `field.examples[0].context` au lieu de
`field.examples[0]`. Mettre à jour `tests/test_mock_tools.py` (ajout de
`key=...`, `examples` enveloppés en `FieldExample`).

**Acceptance criteria :**
- [x] `MockNerExtractor().extract(...)` renvoie toujours le texte de
      l'exemple (désormais via `.context`) comme `value` quand un exemple
      existe, et le message simulé sinon — comportement inchangé

**Verification :**
- [x] Tests : `uv run pytest tests/test_mock_tools.py`

**Dependencies :** Task 1

**Files likely touched :**
- `app/tools/mock_ner.py`
- `tests/test_mock_tools.py`

**Estimated scope :** XS (2 fichiers)

---

## Checkpoint : Phase 1 — Modèle, persistance et extraction (mock + réel) verts
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] Extraction en mode mock toujours fonctionnelle dans le navigateur
      (aucune régression observable)

---

## Task 5 : Formulaire champs — inputs Clé/Section

**Description :** Ajouter les inputs `Label("Clé") + Input(name="key",
required=True)` et `Label("Section") + Input(name="section")` dans
`field_create_form` et `field_row` (app/ui/components.py), positionnés avant
le titre. Mettre à jour les handlers `POST /fields` et
`POST /fields/{id}/update` (app/routes/fields.py) pour lire `key` (requis) et
`section` (optionnel, défaut `None` si vide) et les passer à
`FieldCreate`/`FieldUpdate`.

**Acceptance criteria :**
- [x] Le formulaire de création affiche les inputs Clé et Section
- [x] Le formulaire d'édition d'un champ existant pré-remplit sa clé et sa
      section actuelles
- [x] Créer un champ via l'UI avec une clé déjà existante affiche le banner
      d'erreur (pas de 500) — vérifie le branchement du `ValueError` de la
      Tâche 2
- [x] Créer/éditer un champ sans section fonctionne (section reste vide/null)

**Verification :**
- [x] Tests : `uv run pytest tests/test_fields_routes.py`
- [x] Manuel : créer un champ avec une clé, l'éditer, vérifier la
      persistance après rechargement de `/fields`

**Dependencies :** Task 2

**Files likely touched :**
- `app/ui/components.py`
- `app/routes/fields.py`

**Estimated scope :** S (2 fichiers)

---

## Checkpoint : Phase 2 — UI manuelle mise à jour
- [x] Création/édition manuelle d'un champ fonctionnelle avec Clé/Section
      dans le navigateur

---

## Task 6 : `app/fields_import.py` — parsing + validation tout-ou-rien

**Description :** Nouveau module pur (aucune dépendance FastHTML/sqlite3).
Ajouter `pandas` et `openpyxl` aux dépendances directes (`uv add pandas
openpyxl`). Constante `REQUIRED_COLUMNS = {"section", "label", "Nom",
"Définition", "Type", "exemple valeur", "Exemple texte", "source"}` (colonnes
en plus tolérées). Modèle Pydantic `_ImportRow` avec alias sur les colonnes
françaises, `type` normalisé (`TEXT/INT/FLOAT/BOOLEAN/DATE`, insensible à la
casse → `text/int/float/bool/date`, erreur explicite sinon). Fonction
`import_fields(content: bytes, filename: str) -> ImportResult` où
`ImportResult` est soit `{fields: list[FieldCreate]}` soit
`{errors: list[str]}` (jamais les deux) :
1. Détection du format par extension (`.csv` virgule, `.tsv` tabulation via
   `csv.DictReader`, `.xlsx` via `pandas.read_excel` + `openpyxl`).
2. Colonnes requises absentes → une erreur unique listant les colonnes
   manquantes, aucune ligne parsée.
3. Chaque ligne validée via `_ImportRow` ; toute erreur (type invalide,
   colonne requise vide) → ajoutée à `errors` avec le numéro de ligne et le
   `key`, mais le parsing continue pour collecter *toutes* les erreurs avant
   de rejeter.
4. `errors` non vide → tout est rejeté, `fields` est vide.
5. Sinon, une ligne devient un `FieldCreate` (`key=label`, `title=Nom`,
   `definition=Définition`, `type` normalisé, `section=section`,
   `examples=[FieldExample(context="Exemple texte", value="exemple valeur",
   source=source)]`). Un `key` apparaissant plusieurs fois dans le fichier :
   la dernière occurrence l'emporte (pas de rejet spécifique).

**Acceptance criteria :**
- [x] `import_fields()` sur le vrai `"DATASET GOLD.csv"` (racine du repo, 96
      lignes) renvoie 96 `FieldCreate` et zéro erreur, y compris la ligne au
      texte multi-lignes/guillemets imbriqués
- [x] Fichier avec une colonne manquante → une seule erreur listant
      exactement la/les colonne(s) manquante(s), `fields` vide
- [x] Fichier avec une ligne `Type` invalide (ex. `"PERCENT"`) → import
      rejeté, `fields` vide, l'erreur mentionne la ligne/le `key` concerné
- [x] Même contenu en `.csv`, `.tsv` et `.xlsx` produit les mêmes
      `FieldCreate` (test de conversion factice `.xlsx` via `openpyxl`)
- [x] Colonnes en plus dans le fichier n'empêchent pas l'import

**Verification :**
- [x] Tests : `uv run pytest tests/test_fields_import.py`

**Dependencies :** Task 1

**Files likely touched :**
- `app/fields_import.py` (nouveau)
- `tests/test_fields_import.py` (nouveau)
- `pyproject.toml`
- `uv.lock`

**Estimated scope :** M (nouveau module + tests)

---

## Task 7 : Route `POST /fields/import`

**Description :** Ajouter la route dans `app/routes/fields.py` : reçoit un
`UploadFile`, lit les bytes, appelle `fields_import.import_fields`. Si
`errors`, retourne la page `/fields` avec un `error_banner` listant tous les
messages (une ligne par erreur). Sinon, boucle sur `fields` et appelle
`field_repo.upsert_by_key(...)` pour chacun (commit par appel, cohérent avec
le style déjà en place dans `FieldRepository`), puis redirige vers
`/fields`.

**Acceptance criteria :**
- [x] Upload du vrai `"DATASET GOLD.csv"` puis `field_repo.list_all()`
      contient 96 champs
- [x] Upload d'un fichier avec une colonne manquante → `list_all()` inchangé
      (rien n'est écrit), page d'erreur affichée listant la colonne
      manquante
- [x] Ré-upload du même fichier deux fois de suite → toujours 96 champs (pas
      de doublons, remplacement confirmé)
- [x] Ré-upload d'une version modifiée (une `Définition` changée, même
      `label`) → le champ correspondant est mis à jour, pas dupliqué

**Verification :**
- [x] Tests : `uv run pytest tests/test_fields_routes.py`

**Dependencies :** Task 6, Task 2

**Files likely touched :**
- `app/routes/fields.py`
- `tests/test_fields_routes.py`

**Estimated scope :** S (2 fichiers)

---

## Task 8 : UI — formulaire d'upload sur `/fields`

**Description :** Ajouter `field_import_form()` (app/ui/components.py) :
`Input(type="file", name="file", accept=".csv,.tsv,.xlsx", required=True)` +
bouton "Importer", `action="/fields/import"`, `method="post"`. Insérer la
carte juste après `field_create_form()` et avant la liste des champs sur la
page `/fields` (app/routes/fields.py), cohérent avec l'ordre
création-avant-liste déjà en place.

**Acceptance criteria :**
- [x] `/fields` affiche le formulaire d'upload avec les 3 extensions
      acceptées
- [x] Sélectionner et uploader le vrai `"DATASET GOLD.csv"` depuis le
      navigateur met à jour la liste des champs affichée

**Verification :**
- [x] Manuel : upload réel dans le navigateur (couverture automatisée déjà
      apportée par la Tâche 7 au niveau route)

**Dependencies :** Task 7

**Files likely touched :**
- `app/ui/components.py`
- `app/routes/fields.py`

**Estimated scope :** XS (2 fichiers)

---

## Checkpoint final
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] `uv run python scripts/reset_db.py --yes` puis import réel de
      `"DATASET GOLD.csv"` via l'UI dans le navigateur — 96 champs en base,
      `key`/`section`/`examples` correctement peuplés
- [x] Revue avec l'utilisateur
