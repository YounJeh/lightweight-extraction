# Task List : Validation + export du gold dataset depuis une extraction

Plan : [tasks/plan-gold-export-from-extraction.md](plan-gold-export-from-extraction.md)

---

## Task 1 : `ner_langextract.py` — une ligne par champ demandé, y compris sans candidat

**Description :** Dans `_extract` (`app/tools/ner_langextract.py`), après la
boucle actuelle sur `candidates_by_field.items()`, ajouter un
`ExtractionResult` pour chaque `field` de `fields` qui n'a pas généré de
ligne (aucun candidat groundé) : `field_title=field.title`, `value=""`,
`source="langextract"`, `value_type=field.type`, `typed_value=None`,
`type_error=None`, `page_number=None`, `text_position=None`. L'ordre des
champs déjà trouvés ne change pas ; les champs non détectés sont ajoutés à
la suite. Le mock extractor (`app/tools/mock_ner.py`) n'est pas concerné —
il produit déjà toujours une valeur par champ.

**Acceptance criteria :**
- [x] `extract()` avec 3 champs demandés dont 1 sans candidat dans le texte
      renvoie 3 `ExtractionResult` (pas 2) ; celui du champ non détecté a
      `value == ""` et `typed_value is None`
- [x] `extract()` avec tous les champs détectés a un comportement
      strictement inchangé (mêmes résultats qu'avant la Tâche)
- [x] Deux champs demandés, aucun détecté → 2 `ExtractionResult` à
      `value == ""`, pas d'exception

**Verification :**
- [x] Tests : `uv run pytest -m "not live" tests/test_ner_langextract_typed_hint.py tests/test_ner_langextract_dedupe.py`

**Dependencies :** None

**Files likely touched :**
- `app/tools/ner_langextract.py`
- `tests/test_ner_langextract_dedupe.py` (ou nouveau test dédié si plus
  clair)

**Estimated scope :** XS (1-2 fichiers)

---

## Checkpoint : Phase 1
- [x] `uv run pytest -m "not live"` passe

---

## Task 2 : `app/gold_export.py` — upsert-fusion par `source_file`

**Description :** Nouveau module pur, aucune dépendance FastHTML/sqlite3.
`export_to_gold(yaml_path: Path, *, source_file: str, annotations:
dict[str, dict]) -> GoldExportResult` où `annotations` est déjà au format
gold (`{field_key: {"value": ..., "evidence": {"text": None, "page":
None}}}`, valeur `None` acceptée) :
1. Charger le YAML (`yaml.safe_load`) — fichier absent ou `dataset` vide
   toléré, traité comme une liste vide.
2. `annotations` vide → lever `GoldExportError("aucun champ coché")`, rien
   n'est écrit.
3. Chercher un document existant par `source_file` (comparaison exacte).
   - Trouvé : fusionner (`dict.update`) les nouvelles `annotations` dans
     `document["annotations"]` existant — les clés déjà présentes et non
     renvoyées cette fois restent inchangées. `document_id` inchangé.
   - Absent : nouveau document,
     `document_id = max((d["document_id"] for d in documents), default=0) + 1`,
     `human_validation: True`, `annotations` = celles fournies.
4. Réécrire le YAML en entier (`yaml.safe_dump(..., sort_keys=False,
   allow_unicode=True, default_flow_style=False)`), documents triés par
   `document_id` croissant.
5. Retourner `GoldExportResult(document_id: int, created: bool,
   field_keys: list[str])` (`created` = nouveau document ou mise à jour).

**Acceptance criteria :**
- [x] Sur un YAML de test (copié dans `tmp_path`, jamais le fichier réel) à
      2 documents : exporter un `source_file` inédit ajoute un 3e document
      avec `document_id = 3` (si le max existant est 2), `human_validation:
      true`, et exactement les `annotations` fournies
- [x] Exporter un `source_file` déjà présent avec un sous-ensemble de champs
      fusionne : les champs déjà annotés et non renvoyés cette fois restent
      inchangés, ceux renvoyés sont ajoutés/écrasés, `document_id` ne change
      pas
- [x] `annotations={}` lève `GoldExportError`, le fichier n'est pas modifié
- [x] Une valeur `None` dans `annotations` est bien écrite comme `value:
      null` dans le YAML relu (pas la chaîne `"None"`)
- [x] Recharger le fichier après export avec `yaml.safe_load` renvoie une
      structure valide, cohérente avec `scripts/gold_dataset_sync.py:
      _load_gold_documents` (même clé racine `dataset`)

**Verification :**
- [x] Tests : `uv run pytest tests/test_gold_export.py` — tous les tests
      opèrent sur une copie du YAML dans `tmp_path` (fixture `pytest`,
      jamais `tests/data/dataset_gold_devis.yaml` directement)

**Dependencies :** None

**Files likely touched :**
- `app/gold_export.py` (nouveau)
- `tests/test_gold_export.py` (nouveau)

**Estimated scope :** M (nouveau module + tests)

---

## Checkpoint : Phase 2
- [x] `uv run pytest -m "not live"` passe

---

## Task 3 : Page de résultat — cases à cocher + édition de la valeur

**Description :** Dans `extraction_result()` (`app/ui/components.py`),
envelopper le tableau dans un `Form(action=f"/extraction/runs/{run.id}/export-gold",
method="post")`. Ajouter une colonne case à cocher par ligne
(`name="export_fields"`, `value=field_key`) résolue via un `title_to_key`
construit à partir de `field_repo.list_all()` (même pattern que
`scripts/gold_dataset_eval.py:117`) passé en paramètre de la fonction (la
route devra le fournir). Une ligne dont le `field_title` n'a pas de
correspondance dans `title_to_key` n'affiche pas de case à cocher (pas
exportable). Remplacer la cellule valeur par un `Input(name="value__{field_key}",
value=displayed_value or "")` modifiable. Ajouter une case globale
"Tout cocher/décocher" au-dessus du tableau, avec un script vanilla JS
scopé à cette table (nouveau, distinct de `_field_group_selection_script`
pour éviter toute collision d'id). Bouton "Exporter vers le gold" en pied
de tableau. Une valeur affichée vide (champ non détecté, Tâche 1) doit
afficher un placeholder lisible (ex. `placeholder="—"`) plutôt qu'un champ
vide ambigu.

**Acceptance criteria :**
- [x] La page de résultat d'un run avec un champ non détecté affiche bien
      une ligne pour ce champ (valeur vide, case décochée par défaut)
- [x] Cocher/décocher la case globale coche/décoche toutes les lignes
- [x] Modifier la valeur d'une ligne dans le navigateur avant de soumettre
      le formulaire envoie la valeur modifiée (pas l'originale) au POST
- [x] Aucune case cochée par défaut à l'ouverture de la page (l'utilisateur
      choisit explicitement quoi exporter)

**Verification :**
- [x] Manuel : ouvrir `/extraction/runs/{id}` dans le navigateur (run
      existant), vérifier l'affichage des cases, du toggle global, et de
      l'édition de valeur (couverture automatisée apportée par la Tâche 4
      au niveau route)

**Dependencies :** Task 1 (pour voir une vraie ligne à valeur vide)

**Files likely touched :**
- `app/ui/components.py`

**Estimated scope :** M (1 fichier, mais plusieurs éléments UI + script)

---

## Task 4 : Route `POST /extraction/runs/{id}/export-gold`

**Description :** Dans `app/routes/extraction.py`, nouvelle route qui : lit
le run (`run_repo.get_run(id)`), construit `title_to_key` depuis
`field_repo.list_all()`, parse le form POST (`export_fields` = liste des
`field_key` cochées, `value__{field_key}` = valeur éventuellement corrigée
pour chacune). Pour chaque `field_key` coché : valeur corrigée si fournie
et non vide, sinon valeur affichée du résultat correspondant ; chaîne vide
convertie en `None` avant export (jamais la chaîne `""` dans le YAML).
Construit `annotations = {field_key: {"value": value_or_none, "evidence":
{"text": None, "page": None}}}` et appelle
`gold_export.export_to_gold(GOLD_YAML_PATH, source_file=run.document_name,
annotations=annotations)`. Affiche une bannière succès (nombre de champs
exportés, `document_id`, créé ou mis à jour) ou une bannière erreur
(`GoldExportError`, ex. rien coché) — retourne directement
`extraction_result(run, ...)` avec la bannière, sans redirection (même
pattern que `_extraction_page_with_error`).

**Acceptance criteria :**
- [x] Cocher 2 champs sur 4, en corriger un, exporter : le YAML de test
      (chemin injecté, jamais le fichier réel — voir Boundaries du plan)
      reçoit une entrée avec exactement ces 2 champs, l'un avec la valeur
      corrigée
- [x] Exporter deux fois le même `document_name` (même run rejoué ou runs
      différents sur le même fichier source) fusionne dans la même entrée
      gold, ne duplique pas de `document_id`
- [x] Soumettre le formulaire sans rien cocher affiche la bannière d'erreur,
      le YAML n'est pas modifié
- [x] Un run introuvable (`id` invalide) ne casse pas la route (comportement
      cohérent avec `get_run` existant)

**Verification :**
- [x] Tests : `uv run pytest tests/test_extraction_routes.py` — le chemin
      YAML est un `tmp_path`/fixture dédiée injectée dans le test, jamais
      `tests/data/dataset_gold_devis.yaml`

**Dependencies :** Task 2, Task 3

**Files likely touched :**
- `app/routes/extraction.py`
- `tests/test_extraction_routes.py`

**Estimated scope :** M (2 fichiers)

---

## Checkpoint final
- [x] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue avec l'utilisateur
- [ ] Vérification manuelle réelle (vrai PDF, vrai
      `tests/data/dataset_gold_devis.yaml`) **laissée à l'utilisateur** —
      pas exécutée par moi (CLAUDE.md, corpus gold)
