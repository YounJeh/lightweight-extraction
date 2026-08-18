# Champs typés + valeurs typées à l'extraction

## Problem Statement
Comment permettre à l'utilisateur de déclarer un type (text, int, float, bool, date) pour chaque champ, afin que l'extraction NER produise une valeur validée dans le bon type — en conservant toujours le contexte textuel brut (grounding) même quand le typage échoue ?

## Recommended Direction
Le type devient un attribut du `Field` (comme title/definition/examples aujourd'hui), stocké en base et sélectionnable dans l'UI de gestion des champs.

À l'extraction, deux choses distinctes cohabitent, comme le suggérait l'idée de départ :
- **`extraction_text`** : le grounding textuel brut (citation + position + page), toujours conservé, quel que soit le résultat du typage — c'est la preuve/contexte.
- **valeur typée** : le SDK LangExtract est déjà équipé d'un champ `attributes: dict[str, str | list[str]]` sur `Extraction` (`core/data.py`), actuellement inutilisé. On enrichit le prompt/exemples avec le type attendu pour que le LLM tente de remplir `attributes["value"]` avec une valeur déjà formatée dans le bon type.

On ne fait cependant jamais confiance à cette sortie brute du LLM : une couche de validation Pydantic indépendante (dans `app/tools/`, découplée du `NerExtractor` Protocol) coerce systématiquement `attributes["value"]` (ou à défaut `extraction_text`) vers le type Python attendu (`int`, `float`, `bool`, `date`, `str`). Si la coercion échoue, le champ est signalé en erreur plutôt que silencieusement ignoré ou forcé.

Conséquence du choix de ne pas re-valider l'historique : `value_type` et `type_error` sont **figés au moment de l'extraction** sur chaque ligne de `extraction_results` (nouvelles colonnes), pas recalculés à l'affichage à partir du type courant du `Field`. Un changement de type ultérieur sur un `Field` n'affecte donc jamais le statut des runs déjà exécutés.

## Key Assumptions to Validate
- [ ] Le LLM produit des dates dans un format suffisamment cohérent pour un parsing simple — sinon, forcer un format ISO explicite dans le prompt ou utiliser un parseur permissif (`dateutil`).
- [ ] Les booléens en langage naturel ("oui"/"non", "présent"/"absent") nécessitent une normalisation dédiée côté code avant coercion — `bool("non")` est truthy en Python natif, donc `bool()` brut est un piège à éviter explicitement dans l'implémentation.
- [ ] Le taux d'échec de coercion reste faible en pratique sur des documents réels — si trop de lignes finissent en erreur, la tolérance "rejeter et signaler" (validée par toi) devra peut-être évoluer vers une coercition plus tolérante.

## MVP Scope
**In :**
- `type: Literal["text", "int", "float", "bool", "date"]` sur `Field` (modèle + colonne SQLite, défaut `"text"`).
- `value_type` et `type_error: str | None` sur `ExtractionResult` (colonnes SQLite, figées à l'extraction).
- Enrichissement du prompt LangExtract avec le type attendu par champ.
- Coercion/validation Pydantic indépendante après extraction (fichier dédié, testable isolément).
- UI : sélecteur de type dans le formulaire de champ ; colonne type + valeur typée (ou message d'erreur) dans le tableau de résultats.
- Test pytest de la logique de coercion pour chaque type, y compris les cas d'échec.

**Out (voir Not Doing) :**
- Champs multi-valeurs / listes typées.
- Enum / liste de choix contrainte.
- Coercition tolérante (nettoyage heuristique de type "environ 30" → 30).
- Re-validation rétroactive des runs existants lors d'un changement de type.

## Not Doing (and Why)
- **Enum/liste de choix contrainte** — mentionné comme option mais pas retenu maintenant : ajoute un modèle de configuration supplémentaire (liste de valeurs autorisées) sans être demandé explicitement ; peut venir en fast-follow si un besoin concret apparaît.
- **Champs multi-valeurs (liste typée)** — le modèle actuel (`value: str` singulier) ne le supporte pas et ce n'est pas dans la demande initiale ; le traiter maintenant complexifierait le schéma pour un besoin non confirmé.
- **Coercition tolérante/heuristique** — tu as explicitement choisi "rejeter et signaler" plutôt que "tenter de nettoyer" : plus simple, plus prévisible, et évite d'introduire une logique de parsing fragile et difficile à tester.
- **Re-validation de l'historique au changement de type** — tu as choisi de ne pas re-valider ; implique de figer `value_type`/`type_error` par ligne plutôt que de les dériver du `Field` courant à l'affichage.

## Decisions
- **Coercion** : nouveau module dédié `app/tools/type_coercion.py`, découplé du `NerExtractor` Protocol et testable isolément.
- **Migration DB** : `ALTER TABLE` ponctuel dans `init_db` (pas d'outillage de migration type Alembic) — cohérent avec l'absence de données de production réelles à ce stade.
- **UI erreurs** : badge/couleur distincte sur les lignes en `type_error` dans le tableau de résultats, plutôt qu'un simple texte d'erreur dans la cellule valeur — rend les échecs de typage visibles au premier coup d'œil.
