# Spec : Déduplication des résultats d'extraction

## Objectif

Bug rapporté : lors d'une extraction, un même champ apparaît plusieurs fois
dans les résultats, avec des valeurs différentes. L'utilisateur soupçonne
plusieurs passes LangExtract. Corriger pour qu'un champ sélectionné produise
**une seule** `ExtractionResult` dans l'affichage final.

**Succès =** pour un run donné, `run.results` contient au plus un résultat
par `field_title` sélectionné.

## Root cause (validée)

Pas des « passes » (`extraction_passes=1`, jamais modifié) mais du
**chunking** : `langextract.extract()` découpe le texte en fenêtres de
`max_char_buffer` caractères (défaut 1000) et interroge le modèle
séparément sur chaque fenêtre avec le prompt complet (tous les champs).
Confirmé par inspection directe de `.venv/.../langextract/annotation.py`
et des données déjà en base (`data/app.db`, runs 6/7/9/10 : exactement une
`ExtractionResult` par champ et par chunk).

Deux sources de doublons distinctes, visibles dans les données réelles :

1. **Chunks sans la valeur** : le modèle émet quand même une `Extraction`
   pour la classe (probablement parce que le seul exemple few-shot montre
   un champ toujours renseigné), avec `extraction_text` vide ou un texte
   du type `>>Aucune valeur présente pour X<<`. Dans les deux cas,
   `char_interval is None` — c'est la sémantique documentée de LangExtract
   (`char_interval: None when the extraction text could not be located in
   the source document`, `langextract/data.py`). Ce sont de faux positifs,
   jamais des valeurs à garder.
2. **Chunks avec la valeur, plusieurs fois** : le champ est réellement
   identifiable dans plus d'une fenêtre de texte (ex. clause répétée/
   reformulée ailleurs dans le document) → plusieurs `Extraction` avec
   `char_interval` valide mais des `extraction_text` différents pour le
   même `field_title`.

`LangExtractNerExtractor.extract()` actuel ajoute aujourd'hui *chaque*
`Extraction` retournée sans filtrage ni déduplication → N résultats par
champ, N = nombre de chunks ayant produit quelque chose.

## Décision de correction (mise à jour — arbitrage LLM)

1. **Filtrer** : ignorer toute `Extraction` dont `char_interval is None`
   ou dont `extraction_text` est vide/blanc — ce sont les faux positifs du
   cas 1, jamais affichables.
2. **Sélectionner, par champ, selon le nombre de candidats groundés
   restants** :
   - **0 candidat** → le champ n'apparaît pas dans les résultats (`None`).
   - **1 candidat** → accepté directement, aucun appel LLM.
   - **N candidats, même valeur normalisée** (`strip().lower()`, espaces
     réduits) → fusion silencieuse, on garde la première occurrence
     (`char_interval.start_pos` le plus petit) ; aucun appel LLM, ce n'est
     pas un vrai conflit.
   - **N candidats, valeurs distinctes après normalisation** → **arbitrage
     par un second appel LLM** (`_arbitrate`, réutilise `langextract.extract`
     avec un prompt dédié) : les candidats distincts sont listés, le modèle
     recopie mot pour mot celui qui correspond le mieux à la définition du
     champ. Si la réponse ne correspond exactement à aucun candidat (échec
     de parsing), repli déterministe sur la première occurrence plutôt que
     de perdre le champ.

Le fix reste **entièrement interne à `app/tools/ner_langextract.py`** :
aucun changement de `Protocol`, de route, d'UI ou de schéma DB — cohérent
avec les Boundaries de `specs/pdf-ner-real.md`. L'arbitrage réutilise
`langextract.extract()` (même mécanisme, même clé API/modèle déjà
résolus) plutôt que d'intégrer un second SDK LLM — pas de nouvelle
dépendance, un seul point d'accès LLM dans le fichier.

## Testing Strategy

- Tests **offline** (pas d'appel réseau), `tests/test_ner_langextract_dedupe.py` :
  monkeypatch `langextract.extract`, un cas par branche de sélection —
  0 candidat groundé, 1 candidat, N candidats à même valeur normalisée,
  N candidats en conflit réel (vérifie qu'un *second* appel
  `langextract.extract` a bien lieu, avec le bon `prompt_description`), et
  repli sur la première occurrence si l'arbitrage renvoie un texte qui ne
  correspond à aucun candidat.
- Le test live existant (`tests/test_ner_langextract_live.py`,
  `@pytest.mark.live`) reste inchangé et sert de garde-fou end-to-end avec
  le vrai modèle — revérifié après ce changement (1 passed).
- Pas de migration de données : les doublons déjà en base (runs existants)
  ne sont pas nettoyés rétroactivement — seuls les nouveaux runs sont
  affectés. *Point ouvert si l'utilisateur veut aussi un script de
  nettoyage des runs existants.*

## Boundaries

- **Toujours faire :** garder `NerExtractor.extract()` avec la même
  signature ; ne pas toucher `app/routes/`, `app/ui/`, `app/db.py`.
- **Ne jamais faire :** supprimer/modifier les runs existants en base
  sans confirmation explicite.

## Success Criteria

- [x] `LangExtractNerExtractor.extract()` ne retourne jamais plus d'un
      résultat par `field_title` demandé.
      *`_select_candidate` : 1 candidat accepté, valeurs identiques
      fusionnées, valeurs distinctes arbitrées par LLM.*
- [x] Les faux positifs non-grounded (vide / placeholder) sont exclus.
      *`_group_grounded_candidates` : filtre
      `char_interval is None or not extraction_text.strip()`.*
- [x] Un vrai conflit (valeurs groundées distinctes) est arbitré par un
      second appel LLM plutôt qu'une règle "premier arrivé" — repli sur la
      première occurrence uniquement si l'arbitrage échoue à parser.
- [x] Test offline dédié, sans appel réseau, passe (`uv run pytest -m "not live"`).
      *`tests/test_ner_langextract_dedupe.py`, 5 tests, une branche par cas
      de `_select_candidate`/`_arbitrate`.*
- [x] Aucune régression sur la suite existante.
      *51 passed, 1 deselected — mêmes 2 échecs pré-existants sur
      `test_extraction_routes.py`, confirmés présents avant ce fix. Test
      live (`-m live`) revérifié avec la vraie clé API : 1 passed.*
