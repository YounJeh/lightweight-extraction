# Plan : Validation + export du gold dataset depuis une extraction

Intent confirmée par `interview-me` (voir conversation, pas de doc séparé —
résumé ci-dessous).

## Vue d'ensemble

Sur la page de résultat d'un run (`/extraction/runs/{id}`), permettre de
cocher/corriger chaque champ extrait — y compris ceux non détectés,
désormais affichés comme lignes à valeur vide — puis d'exporter, via un
bouton manuel, uniquement les champs cochés vers
`tests/data/dataset_gold_devis.yaml`, en upsertant par `source_file`
(fusion, pas de remplacement total) et en incrémentant `document_id` pour
les nouveaux documents.

Résumé de l'intent confirmée :
- Bouton manuel uniquement, jamais d'export automatique.
- Coché = exporté avec sa valeur (éventuellement vide → `null` dans le
  YAML) ; décoché = absent de l'entrée gold (pas de clé, pas de `null`).
- Correction de valeur éphémère (utilisée seulement au moment de l'export,
  jamais persistée en base).
- `evidence.text`/`evidence.page` restent `null` dans cette itération.
- Nouveau `source_file` → nouvelle entrée, `document_id = max + 1`,
  `human_validation: true`. `source_file` existant → upsert par fusion sur
  le même `document_id` (les champs cochés remplacent/complètent, les
  champs déjà présents et non re-cochés restent inchangés).
- Écriture directe sur le fichier local versionné git — perte acceptée si
  l'app tourne ailleurs qu'en local.

## Architecture Decisions

- **`field_title` → `field_key` sans nouvelle colonne DB** : le mapping
  titre humain → clé machine existe déjà dans le repo
  (`scripts/gold_dataset_eval.py:117`,
  `title_to_key = {field.title: field.key for field in fields}`) pour un
  besoin identique (comparer une extraction aux annotations gold). On
  réutilise exactement ce pattern côté route d'export plutôt que d'ajouter
  un `field_key` sur `ExtractionResult`/la table `extraction_results` —
  moins de surface de migration, cohérent avec un risque déjà accepté
  ailleurs dans le code (collision de `title` non gérée, pas pire qu'avant).
- **Champs non détectés : `value=""`, pas de migration DB.**
  `extraction_results.value` est `TEXT NOT NULL` ; `gold_matching._is_present`
  traite déjà `""` comme "absent" (`str(value).strip() != ""`). Émettre une
  chaîne vide pour un champ sans candidat évite toute migration de schéma
  (colonne nullable) tout en restant cohérent avec le reste du pipeline
  d'évaluation. Le mock extractor n'est pas concerné (il produit toujours
  une valeur factice par champ).
- **Module d'export pur (`app/gold_export.py`)** : aucune dépendance
  FastHTML, lit/écrit uniquement le YAML via un `Path` passé en paramètre —
  testable sur une copie temporaire du fichier, jamais sur
  `tests/data/dataset_gold_devis.yaml` réel (voir Boundaries). Upsert par
  `source_file` : fusion du dict `annotations` (`dict.update`), pas de
  remplacement total de l'entrée existante.
- **Pas de redirection après export** : la route retourne directement la
  page de résultat avec une bannière succès/erreur, comme le fait déjà
  `_extraction_page_with_error` pour le formulaire d'extraction — pas de
  mécanisme de flash message à introduire.
- **Sélection collective** : réutilisation du pattern JS vanilla déjà en
  place pour le formulaire de création (`_field_group_selection_script`,
  `app/ui/components.py:207`) — un script scopé à la nouvelle table de
  résultat plutôt qu'un framework JS.

## Ordre d'implémentation

Slicing vertical : d'abord la donnée (champs non détectés visibles), puis
le module d'export pur (testable seul), puis l'UI et la route qui les
relient.

### Phase 1 : Champs non détectés visibles
- [ ] Tâche 1 : `ner_langextract.py` — une ligne par champ demandé, y
      compris sans candidat

### Checkpoint 1
- [ ] `uv run pytest -m "not live"` passe

### Phase 2 : Module d'export pur
- [ ] Tâche 2 : `app/gold_export.py` — upsert-fusion par `source_file`

### Checkpoint 2
- [ ] `uv run pytest -m "not live"` passe (tests sur copie temporaire du
      YAML uniquement — jamais sur le fichier réel, voir Boundaries)

### Phase 3 : UI + route
- [ ] Tâche 3 : page de résultat — cases à cocher (individuelle +
      collective) + édition de la valeur
- [ ] Tâche 4 : route `POST /extraction/runs/{id}/export-gold`

### Checkpoint final
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue avec l'utilisateur, puis **vérification manuelle réelle
      laissée à l'utilisateur** (upload d'un vrai PDF, cocher/corriger,
      exporter, inspecter le vrai `tests/data/dataset_gold_devis.yaml`) —
      pas à moi de la faire (CLAUDE.md : "Ne fais pas de run de
      vérification sur le corpus gold. C'est uniquement à l'humain de le
      faire.")

## Risques et mitigations

| Risque | Impact | Mitigation |
|---|---|---|
| Collision de `title` entre deux champs → mapping `title_to_key` ambigu (même risque que `gold_dataset_eval.py`, pas nouveau) | Faible (aucun cas réel connu) | Documenté, pas corrigé dans ce chantier — cohérent avec le risque déjà accepté ailleurs |
| Réécriture complète du YAML par `yaml.safe_dump` change le formatage (perd les lignes vides entre documents) → gros diff git pour un seul champ modifié | Moyen (lisibilité des diffs) | `sort_keys=False`, ordre des documents par `document_id` croissant, pas de tri des clés d'annotations — limite le diff sans le supprimer ; accepté comme compromis du chantier (l'utilisateur édite aujourd'hui ce fichier à la main, il choisit d'automatiser) |
| Un test qui écrirait par erreur sur le vrai `tests/data/dataset_gold_devis.yaml` corromprait le corpus gold versionné | Élevé | `app/gold_export.py` ne connaît aucun chemin par défaut — le chemin est toujours un paramètre explicite ; tous les tests utilisent `tmp_path`, jamais le fichier réel |
| Ligne "non détectée" (`value=""`) mal affichée dans le tableau existant (`_result_row` utilise `result.typed_value or result.value`) | Faible | Vérifier à la Tâche 3 qu'une valeur vide affiche un placeholder lisible (ex. "—") plutôt qu'une cellule vide ambiguë |

## Points ouverts

Aucun bloquant restant — l'intent a été entièrement tranchée via
`interview-me`. Reste seulement, hors scope explicite de ce chantier :
bridge few-shot LangExtract, `evidence.text`/`evidence.page`, persistance
de la correction de valeur en base.
