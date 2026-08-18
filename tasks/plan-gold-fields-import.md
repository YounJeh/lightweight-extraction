# Plan : Import du dataset gold vers les champs

Idée : [docs/ideas/gold-fields-import.md](../docs/ideas/gold-fields-import.md)

## Vue d'ensemble

Étendre `Field` avec une clé stable (`key`, unique) et une catégorie
(`section`), restructurer `examples` de `list[str]` vers
`list[FieldExample]` (`context`/`value`/`source`), puis livrer un import de
fichier (CSV/TSV/XLSX) sur `/fields` qui valide tout-ou-rien avant d'upserter
par `key`. Le fichier réel (`DATASET GOLD.csv`, 96 lignes) sert de jeu de
validation final.

## Décisions d'architecture

- **`examples` restructuré, pas juste enrichi** : `FieldExample(context:
  str, value: str | None, source: str | None)` — `context` reprend
  exactement le rôle de l'ancien `str` (texte utilisé tel quel par
  `ner_langextract.py`/`mock_ner.py`), donc la Tâche 3 (compat NER) est un
  renommage de forme, zéro changement de comportement observable.
- **Unicité de `key`** via un index unique dédié (`CREATE UNIQUE INDEX IF
  NOT EXISTS idx_fields_key ON fields(key)`) plutôt qu'une contrainte
  `UNIQUE` posée directement dans `ALTER TABLE ADD COLUMN` — SQLite ne
  permet pas d'ajouter une contrainte `UNIQUE` via `ALTER TABLE ADD COLUMN`
  sur une table existante ; un index unique séparé fonctionne dans les deux
  cas (table neuve ou déjà migrée) et reste idempotent.
- **Upsert SQLite natif** : `INSERT ... ON CONFLICT(key) DO UPDATE SET ...`
  dans une nouvelle méthode `FieldRepository.upsert_by_key`, plutôt qu'un
  aller-retour `SELECT` puis `INSERT`/`UPDATE` — plus simple, atomique par
  construction.
- **Module d'import pur** : `app/fields_import.py`, aucune dépendance à
  FastHTML/sqlite3 — prend des bytes + nom de fichier, renvoie soit une
  liste de `FieldCreate` valides soit une erreur structurée listant tout ce
  qui cloche (colonnes manquantes et/ou lignes invalides). La route
  `POST /fields/import` (app/routes/fields.py) est la seule à toucher la DB,
  via `upsert_by_key` en boucle sur une même transaction.
- **8 colonnes codées en dur** (contrat v1, voir idée) :
  `section, label, Nom, Définition, Type, exemple valeur, Exemple texte,
  source`. Colonnes en plus tolérées ; toute colonne manquante rejette
  l'import avant même de lire les lignes.
- **`type` normalisé, jamais deviné** : `INT`/`BOOLEAN`/`FLOAT`/`DATE`/`TEXT`
  (insensible à la casse) → `int`/`bool`/`float`/`date`/`text` ; toute autre
  valeur est une erreur de ligne (cohérent avec "rejeter et signaler" déjà
  choisi pour le typage des résultats d'extraction).
- **UI manuelle inchangée dans l'esprit** : le textarea "Exemples (un par
  ligne)" reste tel quel, chaque ligne devient `FieldExample(context=ligne)`
  — pas de refonte du formulaire pour saisir `value`/`source` à la main,
  seuls `key`/`section` s'ajoutent comme nouveaux champs texte.

## Ordre d'implémentation

Slicing vertical : modèle+persistance d'abord (doit rester vert seul), puis
UI manuelle (ne doit jamais casser), puis import (la vraie feature).

### Phase 1 : Modèle & persistance (sans toucher à l'UI d'import)
- [x] Tâche 1 : `FieldExample` + `Field.key`/`Field.section` + migration
- [x] Tâche 2 : `FieldRepository` — CRUD adapté + `upsert_by_key`

### Checkpoint 1a
- [x] `uv run pytest -m "not live"` (modèle + persistance) passe

- [x] Tâche 3 : Compat NER réel — `ner_langextract.py` sur la nouvelle forme
      d'`examples`
- [x] Tâche 4 : Compat NER mock — `mock_ner.py` sur la nouvelle forme
      d'`examples`

### Checkpoint 1
- [x] `uv run pytest -m "not live"` passe
- [x] Extraction en mode mock toujours fonctionnelle dans le navigateur

### Phase 2 : UI manuelle (ne doit pas casser la création/édition)
- [x] Tâche 5 : Formulaire champs — inputs Clé/Section

### Checkpoint 2
- [x] Créer/éditer un champ à la main dans l'UI fonctionne avec les nouveaux
      inputs

### Phase 3 : Import de fichier
- [x] Tâche 6 : `app/fields_import.py` — parsing + validation tout-ou-rien
- [x] Tâche 7 : Route `POST /fields/import` — upsert transactionnel
- [x] Tâche 8 : UI — formulaire d'upload sur `/fields`

### Checkpoint final
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] `uv run python scripts/reset_db.py --yes` puis import réel de
      `DATASET GOLD.csv` (96 lignes) via l'UI — vérifier en base que les 96
      champs sont présents avec `key`/`section`/`examples` correctement
      peuplés, y compris la ligne au texte multi-lignes/guillemets imbriqués
- [x] Revue avec l'utilisateur

## Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| `field.examples[0]` cassé silencieusement par le changement de forme (déjà utilisé par `ner_langextract.py`/`mock_ner.py`) | Élevé (casse l'extraction en prod) | Tâches 3 et 4 dédiées, avant tout travail sur l'import ; tests existants (`test_ner_langextract_typed_hint.py`, `test_ner_langextract_dedupe.py`, `test_mock_tools.py`) mis à jour et gardés verts |
| Ligne au format CSV inhabituel (guillemets imbriqués `"""..."""` dans "Exemple texte") mal parsée | Moyen | `csv.DictReader` stdlib gère nativement le RFC 4180 ; vérification manuelle explicite de cette ligne précise au checkpoint final |
| `openpyxl` ajouté comme nouvelle dépendance directe alors que `pandas` n'est aujourd'hui que transitif (via `langextract`) | Faible | Les deux ajoutés explicitement à `pyproject.toml` via `uv add` (Tâche 5), pas de version implicite |
| Import partiel si une erreur survient après le début de l'upsert (violerait le "tout ou rien") | Élevé si non testé | Toute la validation (colonnes + lignes) se fait avant la première écriture DB (Tâche 5, module pur sans I/O DB) ; upserts Tâche 6 dans une seule transaction |
| Un `key` dupliqué dans le même fichier (n'arrive pas dans `DATASET GOLD.csv`, 96 clés uniques vérifiées) | Faible | Dernière occurrence dans le fichier gagne avant upsert ; pas de rejet spécifique — comportement documenté en commentaire, pas testé en profondeur (cas non présent dans les données réelles) |

## Points ouverts

- Aucun bloquant produit restant : migration ("repartir d'une base vide") et
  politique de doublon ("remplacer") tranchées par toi. Reste ouvert
  seulement le fast-follow explicitement mis hors scope (bridge LangExtract,
  script CLI) — voir "Not Doing" dans l'idée.
