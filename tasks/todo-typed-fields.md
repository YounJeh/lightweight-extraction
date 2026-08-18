# Task List : Champs typés + valeurs typées à l'extraction

Plan : [tasks/plan-typed-fields.md](plan-typed-fields.md) ·
Idée : [docs/ideas/typed-fields.md](../docs/ideas/typed-fields.md)

---

## Task 1 : Modèle `Field.type` + schéma/migration `fields`

**Description :** Ajouter un alias `FieldType = Literal["text", "int",
"float", "bool", "date"]` et un champ `type: FieldType = "text"` sur
`FieldBase` dans `app/models.py`. Ajouter la colonne `type TEXT NOT NULL
DEFAULT 'text'` à la définition `CREATE TABLE fields` dans `app/db.py`, et
ajouter dans `init_db` une migration idempotente (`PRAGMA table_info(fields)`
→ `ALTER TABLE fields ADD COLUMN type TEXT NOT NULL DEFAULT 'text'` si la
colonne est absente) pour ne pas casser une DB locale déjà créée avec
l'ancien schéma.

**Acceptance criteria :**
- [x] `Field(...)` sans `type` explicite vaut `"text"` par défaut
- [x] `Field(type="int")` (et `float`/`bool`/`date`) est accepté
- [x] `Field(type="autre_chose")` lève une `ValidationError`
- [x] `init_db()` sur une DB neuve crée `fields.type` directement
- [x] `init_db()` sur une DB dont la table `fields` existe déjà sans colonne
      `type` (schéma pré-migration) ajoute la colonne sans erreur ni perte
      de données, et un second appel à `init_db()` reste sans effet
      (idempotent)

**Verification :**
- [x] Tests : `uv run pytest tests/test_models.py tests/test_db.py`
- [x] Build : `uv run pytest -m "not live"` (suite complète, pas de régression)

**Dependencies :** None

**Files likely touched :**
- `app/models.py`
- `app/db.py`
- `tests/test_models.py`
- `tests/test_db.py`

**Estimated scope :** S (2-3 fichiers)

---

## Task 2 : `FieldRepository` persiste/lit `type`

**Description :** Étendre `FieldRepository.create`/`update` (app/repository.py)
pour insérer/mettre à jour la colonne `type`, et `_row_to_field` pour la
relire. Aucun changement de signature publique au-delà de ce que `Field`
expose déjà (Task 1).

**Acceptance criteria :**
- [x] `repo.create(FieldCreate(title=..., definition=..., type="int"))` puis
      `repo.get(id)` renvoie `type == "int"`
- [x] `repo.update(id, FieldUpdate(..., type="date"))` change bien le type
      persisté
- [x] `repo.create(FieldCreate(title=..., definition=...))` (sans `type`)
      persiste `"text"` par défaut

**Verification :**
- [x] Tests : `uv run pytest tests/test_field_repository.py`

**Dependencies :** Task 1

**Files likely touched :**
- `app/repository.py`
- `tests/test_field_repository.py`

**Estimated scope :** XS (1 fichier + test)

---

## Task 3 : UI champs — sélecteur de type

**Description :** Ajouter un `<select name="type">` (options text/int/
float/bool/date) dans `field_create_form` et `field_row`
(app/ui/components.py), pré-sélectionné sur la valeur courante dans
`field_row`. Mettre à jour les handlers `POST /fields` et
`POST /fields/{id}/update` (app/routes/fields.py) pour lire le paramètre de
formulaire `type` (défaut `"text"`) et le passer à `FieldCreate`/`FieldUpdate`.

**Acceptance criteria :**
- [x] Le formulaire de création affiche les 5 types, `text` sélectionné par
      défaut
- [x] Le formulaire d'édition d'un champ existant pré-sélectionne son type
      actuel
- [x] Créer un champ en choisissant `int` dans l'UI le persiste avec ce type
- [x] Modifier le type d'un champ existant via l'UI met à jour la valeur
      persistée

**Verification :**
- [x] Tests : `uv run pytest tests/test_fields_routes.py`
- [x] Manuel : lancer l'app, créer un champ de type `date`, le modifier en
      `bool`, vérifier l'état affiché après rechargement de `/fields`

**Dependencies :** Task 2

**Files likely touched :**
- `app/ui/components.py`
- `app/routes/fields.py`
- `tests/test_fields_routes.py`

**Estimated scope :** S (2 fichiers + test)

---

## Checkpoint : Phase 1 — Type de champ bout en bout
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] Vérification manuelle des 5 types dans l'UI de gestion des champs
- [ ] Revue avec l'utilisateur avant d'attaquer la Phase 2

---

## Task 4 : `ExtractionResult.value_type` / `type_error`

**Description :** Ajouter `value_type: FieldType | None = None` et
`type_error: str | None = None` à `ExtractionResult` (app/models.py). Les
deux restent optionnels pour ne pas casser les usages existants (Mock actuel,
runs déjà en base sans ces colonnes tant que Task 5 n'est pas faite).

**Acceptance criteria :**
- [x] `ExtractionResult(field_title=..., value=...)` reste valide sans
      `value_type`/`type_error` (les deux valent `None`)
- [x] `ExtractionResult(..., value_type="int", type_error=None)` est accepté
- [x] `ExtractionResult(..., value_type="int", type_error="valeur non
      convertible en int")` est accepté

**Verification :**
- [x] Tests : `uv run pytest tests/test_models.py`

**Dependencies :** Task 1 (réutilise `FieldType`)

**Files likely touched :**
- `app/models.py`
- `tests/test_models.py`

**Estimated scope :** XS (1 fichier + test)

---

## Task 5 : Colonnes + migration `extraction_results`, `ExtractionRunRepository`

**Description :** Ajouter `value_type TEXT` et `type_error TEXT` (nullable)
à `CREATE TABLE extraction_results` dans `app/db.py`, plus la migration
idempotente correspondante dans `init_db` (même mécanisme que Task 1). Mettre
à jour `ExtractionRunRepository.create_run` (INSERT) et `get_run` (SELECT +
reconstruction `ExtractionResult`) dans `app/extraction_repository.py` pour
écrire/lire ces deux colonnes.

**Acceptance criteria :**
- [x] `init_db()` migre une DB existante dont `extraction_results` n'a pas
      encore `value_type`/`type_error`, sans perte des runs déjà stockés
- [x] `create_run` avec des `ExtractionResult` portant `value_type`/
      `type_error` les persiste
- [x] `get_run` renvoie des `ExtractionResult` avec `value_type`/`type_error`
      identiques à ceux insérés
- [x] `get_run` sur un run inséré avant migration (colonnes `NULL`) renvoie
      `value_type=None, type_error=None` sans erreur

**Verification :**
- [x] Tests : `uv run pytest tests/test_db.py tests/test_extraction_repository.py`

**Dependencies :** Task 4

**Files likely touched :**
- `app/db.py`
- `app/extraction_repository.py`
- `tests/test_db.py`
- `tests/test_extraction_repository.py`

**Estimated scope :** S (2 fichiers + tests)

---

## Checkpoint : Phase 2 — Stockage prêt, pas encore de producteur
- [x] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue rapide avant d'attaquer la logique de coercion (Phase 3, la plus
      à risque)

---

## Task 6 : `app/tools/type_coercion.py`

**Description :** Nouveau module pur, sans dépendance à `langextract`.
Fonction unique `validate(raw: str, field_type: FieldType) -> str | None`
qui renvoie `None` si `raw` est valide pour `field_type`, sinon un message
d'erreur explicite. Règles : `text` toujours valide ; `int`/`float` via
parsing numérique standard (rejette non-numérique) ; `bool` via une table de
tokens explicite insensible à la casse (`oui`/`non`/`vrai`/`faux`/`true`/
`false`/`1`/`0` — **pas** de `bool(str)` brut, qui est truthy pour toute
chaîne non vide y compris `"non"`) ; `date` via `date.fromisoformat`
(format `YYYY-MM-DD` strict pour le MVP, limitation connue documentée dans
le docstring). Chaîne vide/whitespace → invalide pour tous les types sauf
`text`.

**Acceptance criteria :**
- [x] `validate("30", "int")` → `None` ; `validate("environ 30", "int")` →
      message d'erreur
- [x] `validate("3.5", "float")` → `None` ; `validate("trois virgule cinq",
      "float")` → erreur
- [x] `validate("oui", "bool")` → `None` ; `validate("non", "bool")` → `None`
      (et surtout : ne doit **pas** être traité comme valide au sens
      `bool("non") == True`) ; `validate("peut-être", "bool")` → erreur
- [x] `validate("2026-08-14", "date")` → `None` ; `validate("14 août 2026",
      "date")` → erreur
- [x] `validate("", "int")` → erreur ; `validate("", "text")` → `None`
- [x] `validate("n'importe quoi", "text")` → toujours `None`

**Verification :**
- [x] Tests : `uv run pytest tests/test_type_coercion.py` (nouveau fichier,
      un cas succès + un cas échec minimum par type, plus le cas bool piège
      explicitement nommé dans le test)

**Dependencies :** None (peut être fait en parallèle des Tasks 1-5)

**Files likely touched :**
- `app/tools/type_coercion.py` (nouveau)
- `tests/test_type_coercion.py` (nouveau)

**Estimated scope :** S (2 fichiers, logique pure)

---

## Task 7 : `LangExtractNerExtractor` — prompt enrichi + `attributes` + coercion

**Description :** Dans `app/tools/ner_langextract.py` :
`_prompt_description` mentionne le type attendu par champ (texte informatif
dans le prompt, ex. « au format entier », « au format ISO AAAA-MM-JJ » pour
`date`, etc.). `_build_example` attache `attributes={"value": field.examples[0]}`
sur l'`Extraction` d'exemple quand `field.type != "text"` (les champs texte
n'ont pas besoin de ce doublon). Dans `extract()`, après `_select_candidate`,
calculer `raw_value = (chosen.attributes or {}).get("value") or
chosen.extraction_text`, appeler `type_coercion.validate(raw_value,
field.type)`, et renseigner `value_type=field.type` et `type_error=<résultat>`
sur l'`ExtractionResult` construit. `value` continue de recevoir
`chosen.extraction_text` sans changement de comportement existant.

**Acceptance criteria :**
- [x] Un champ `type="int"` dont l'extraction (via `attributes["value"]` ou,
      à défaut, `extraction_text`) est numérique produit `type_error=None`
- [x] Un champ `type="int"` dont la valeur extraite n'est pas convertible
      produit un `type_error` non `None`, sans lever d'exception et sans
      perdre la ligne de résultat (le run continue, `value` reste peuplé
      avec le texte groundé)
- [x] Quand `chosen.attributes` est absent/vide, le fallback sur
      `chosen.extraction_text` est utilisé pour la validation
- [x] `value_type` est toujours égal au `field.type` du champ correspondant
- [x] Aucune régression sur le comportement existant de dédoublonnage/
      arbitrage (tests `test_ner_langextract_dedupe.py` toujours verts)

**Verification :**
- [x] Tests : `uv run pytest tests/test_ner_langextract_dedupe.py` (étendu
      avec des cas typés — `langextract.extract` monkeypatché comme déjà
      fait dans ce fichier)
- [x] `uv run pytest -m "not live"` complet
- [x] `live` (optionnel, si clé API dispo) : `uv run pytest -m live` pour
      confirmer que le prompt enrichi n'empêche pas une extraction réelle
      de fonctionner

**Dependencies :** Task 6, Task 4

**Files likely touched :**
- `app/tools/ner_langextract.py`
- `tests/test_ner_langextract_dedupe.py`

**Estimated scope :** M (1 fichier logique dense + tests, le plus à risque
du plan)

---

## Task 8 : `MockNerExtractor` — cohérence `value_type`/`type_error`

**Description :** Dans `app/tools/mock_ner.py`, `_mock_result` renseigne
`value_type=field.type` et `type_error=None` (le mock rejoue toujours
l'exemple du champ tel quel, donc il « réussit » toujours par construction).

**Acceptance criteria :**
- [x] Le résultat mock d'un champ `type="date"` a `value_type="date"`,
      `type_error=None`

**Verification :**
- [x] Tests : `uv run pytest tests/test_mock_tools.py`

**Dependencies :** Task 4

**Files likely touched :**
- `app/tools/mock_ner.py`
- `tests/test_mock_tools.py`

**Estimated scope :** XS (1 fichier + test)

---

## Checkpoint : Phase 3 — Production de bout en bout
- [x] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue avec l'utilisateur avant l'affichage (Phase 4)

---

## Task 9 : Tableau de résultats — colonne type + badge d'erreur

**Description :** Dans `app/ui/components.py`, ajouter une colonne « Type »
au tableau (`extraction_result`/`_result_row`), affichant `value_type`. Quand
`type_error` est renseigné, styler la ligne ou la cellule valeur avec une
classe d'erreur distincte (ex. `result-value-error`) affichant le message
d'erreur (au moins en `title=` ou texte visible), pour la rendre repérable
au premier coup d'œil dans la liste des résultats — distincte visuellement
du badge `source` déjà existant. Ajouter les règles CSS correspondantes dans
`static/style.css` en réutilisant les variables de couleur existantes
(`--badge-bg`/`--badge-text`) ou une nouvelle paire dédiée à l'erreur,
cohérente avec `.banner-error`.

**Acceptance criteria :**
- [x] Le tableau de résultats affiche une colonne Type avec la valeur de
      `value_type` (ou un placeholder si `None`, cas des anciens runs)
- [x] Une ligne avec `type_error` non `None` est visuellement distincte
      (couleur/badge) des lignes valides
- [x] Une ligne sans erreur ne montre aucun indicateur d'erreur

**Verification :**
- [x] Tests : `uv run pytest tests/test_extraction_routes.py` (assertions
      sur la présence de la classe/texte d'erreur dans le HTML rendu pour un
      run construit avec un résultat en erreur)
- [x] Manuel : lancer l'app (mode mock suffit), exécuter une extraction,
      vérifier visuellement la colonne Type et forcer un cas d'erreur
      (temporairement, via un test ou des données) pour valider le rendu du
      badge

**Dependencies :** Task 7, Task 8

**Files likely touched :**
- `app/ui/components.py`
- `static/style.css`
- `tests/test_extraction_routes.py`

**Estimated scope :** S/M (2-3 fichiers)

---

## Checkpoint : Complete
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] Vérification manuelle en navigateur : création de champs des 5 types,
      extraction (mock), affichage du type et d'une erreur simulée
- [ ] Revue avec l'utilisateur
