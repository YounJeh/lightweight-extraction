# Plan : Champs typés + valeurs typées à l'extraction

Idée : [docs/ideas/typed-fields.md](../docs/ideas/typed-fields.md)

## Vue d'ensemble

Ajouter un `type` (text/int/float/bool/date) sur `Field`, le propager jusqu'à
l'extraction (prompt LangExtract enrichi + attribut `attributes["value"]`),
valider/coercer indépendamment via un nouveau module Pydantic, et figer le
résultat (`value_type`, `type_error`) par ligne `extraction_results` au
moment de l'extraction — jamais recalculé après coup.

## Décisions d'architecture

- **Coercion découplée** : `app/tools/type_coercion.py`, nouveau module pur
  (aucune dépendance à langextract), appelé depuis `LangExtractNerExtractor`
  et `MockNerExtractor`, jamais depuis les routes/UI.
- **Migration DB** : `ALTER TABLE ... ADD COLUMN` ponctuel dans `init_db`
  (pas d'outillage de migration) — cohérent avec l'absence de données de
  production réelles et le style `CREATE TABLE IF NOT EXISTS` déjà en place.
- **`value` ne change pas de sémantique** : reste le texte brut groundé
  (`extraction_text`), affiché tel quel dans la colonne "Valeur" — seuls
  `value_type`/`type_error` sont nouveaux, en parallèle.
- **Bool** : pas de `bool(str)` — table de tokens explicite
  (oui/non/vrai/faux/true/false/1/0), pour éviter le piège `bool("non") ==
  True`.
- **Date** : MVP limité au format ISO (`YYYY-MM-DD`) — pas de dépendance
  `dateutil` ajoutée sans validation préalable (voir hypothèse ouverte dans
  l'idée).

## Ordre d'implémentation

Slicing vertical par couche stable (DB → repo → UI pour les champs, puis DB
→ repo → coercion → extracteurs → UI pour les résultats), pas horizontal —
chaque tâche laisse la suite testable `pytest -m "not live"` verte.

### Phase 1 : Type de champ (bout en bout, sans toucher à l'extraction)
- [x] Tâche 1 : Modèle `Field.type` + schéma/migration `fields`
- [x] Tâche 2 : `FieldRepository` persiste/lit `type`
- [x] Tâche 3 : UI champs — sélecteur de type

### Checkpoint 1
- [x] `uv run pytest -m "not live"` passe
- [x] Création/modification d'un champ avec chaque type fonctionne dans l'UI

### Phase 2 : Stockage des résultats typés (sans producteur encore)
- [x] Tâche 4 : `ExtractionResult.value_type` / `type_error`
- [x] Tâche 5 : Colonnes + migration `extraction_results`, `ExtractionRunRepository`

### Checkpoint 2
- [x] `uv run pytest -m "not live"` passe
- [x] Une DB existante (schéma pré-migration) s'ouvre sans erreur après `init_db`

### Phase 3 : Production de la valeur typée
- [x] Tâche 6 : `app/tools/type_coercion.py` (pur, testé isolément)
- [x] Tâche 7 : `LangExtractNerExtractor` — prompt enrichi + `attributes` + coercion
- [x] Tâche 8 : `MockNerExtractor` — cohérence `value_type`/`type_error`

### Checkpoint 3
- [x] `uv run pytest -m "not live"` passe
- [x] `tests/test_ner_langextract_live.py` (marqué `live`, optionnel) toujours
      cohérent si clé API disponible

### Phase 4 : Affichage
- [x] Tâche 9 : Tableau de résultats — colonne type + badge d'erreur

### Checkpoint final
- [x] `uv run pytest -m "not live"` passe intégralement
- [x] Vérification manuelle dans le navigateur (mode mock suffit) : création
      de champs typés, extraction, affichage du type et d'une erreur simulée
- [ ] Revue avec l'utilisateur

## Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| DB locale existante sans colonnes `type`/`value_type`/`type_error` casse au démarrage | Élevé (bloque l'app) | Migration `ALTER TABLE` idempotente testée sur une DB pré-existante (tests/test_db.py) avant toute autre tâche |
| Le LLM ne remplit pas `attributes["value"]` de façon fiable | Moyen | Fallback systématique sur `extraction_text` si `attributes` absent/vide (Tâche 7) ; à observer en usage réel, pas bloquant pour le MVP |
| Format de date LLM incohérent avec l'ISO strict | Moyen | Limitation documentée comme connue (pas un bug) ; ouvre la porte à `dateutil` en fast-follow si le taux d'erreur est élevé en pratique |
| Piège `bool()` Python sur chaîne non vide | Élevé si non testé | Table de tokens explicite + test dédié couvrant "non"/"faux"/"0" (Tâche 6) |

## Points ouverts

- Aucun bloquant restant côté produit (toutes les questions ouvertes de
  l'idée ont été tranchées). Risque technique résiduel : robustesse du
  parsing de date en usage réel (voir tableau ci-dessus), à observer après
  livraison plutôt qu'à résoudre a priori.
