# Import du dataset gold vers les champs

## Problem Statement
Comment charger en masse un jeu de définitions de champs déjà annotées (clé,
titre, définition, type, section, exemple typé + contexte + source
document) depuis un fichier tableur réel, sans jamais laisser un import
partiel ou invalide corrompre la base de champs ?

## Recommended Direction
`DATASET GOLD.csv` (96 lignes, colonnes `section, label, Nom, Définition,
Type, exemple valeur, Exemple texte, source`) sert de première charge réelle
et fige la forme cible du modèle `Field` :

- **`key`** : slug machine stable (`label` du CSV), distinct du `title`
  humain (`Nom`) — nouvelle colonne, unique.
- **`section`** : catégorie de regroupement (`Condition de règlement`,
  `Pénalité`...) — nouvelle colonne, informative pour l'UI.
- **`examples`** : passe de `list[str]` à `list[{context, value, source}]`
  — remplace le texte libre actuel par la structure que `notes.md` demandait
  déjà (valeur typée + texte de contexte groundé).

L'import (page `/fields`) valide d'abord la présence des 8 colonnes
attendues (erreur listant les manquantes si incomplet, colonnes en plus
tolérées), puis chaque ligne via Pydantic (type normalisé vers
`text/int/float/bool/date`, colonnes requises non vides). **Tout ou rien** :
la moindre ligne invalide rejette l'import complet, rien n'est écrit.
Si le fichier est valide, chaque ligne est **upsertée par `key`** — un `key`
déjà présent en base voit son champ entièrement remplacé (title, definition,
type, section, examples), pas fusionné.

Le bridge vers LangExtract (utiliser `value`/`source` comme few-shot enrichi)
reste explicitement hors scope de cette itération : `ner_langextract.py` et
`mock_ner.py` sont seulement adaptés pour continuer à fonctionner à
l'identique avec la nouvelle forme (lecture de `.context` au lieu d'une
string brute) — aucun changement de comportement observable de
l'extraction.

## Key Assumptions to Validate
- [ ] Le futur import (hors ce CSV précis) respectera la même forme de 8
      colonnes françaises — si un fichier différent doit être supporté un
      jour, le mapping colonnes → modèle devra devenir configurable.
- [ ] Une seule ligne par `key` dans un même fichier suffit en pratique
      (vrai pour ce CSV) — pas de logique de fusion multi-lignes pour un
      même champ dans cette itération.
- [ ] `pandas`/`openpyxl` (xlsx) restent un coût de dépendance acceptable
      pour ce projet "pipeline le plus simple possible" — tranché par toi en
      faveur de xlsx dès la v1.

## MVP Scope
**In :**
- `Field.key` (unique), `Field.section`, `Field.examples: list[FieldExample]`
  (modèle + migration idempotente SQLite).
- Formulaire manuel de champ (création/édition) mis à jour avec Clé/Section.
- Module d'import pur (CSV/TSV/XLSX), validation Pydantic stricte,
  tout-ou-rien, upsert-par-clé en remplacement.
- Route + UI d'upload sur `/fields`.
- Compat minimale `ner_langextract.py`/`mock_ner.py` (pas de régression).
- Vérification manuelle : `scripts/reset_db.py` puis import réel de
  `DATASET GOLD.csv` (96 lignes).

**Out (voir Not Doing) :**
- Utilisation des exemples structurés comme few-shot enrichi dans le prompt
  LangExtract.
- Script CLI d'import headless (`scripts/import_fields.py`).
- Mapping de colonnes configurable pour d'autres formats de fichier.
- Fusion/merge d'examples entre plusieurs imports du même `key`.

## Not Doing (and Why)
- **Bridge LangExtract (few-shot enrichi)** — tu as choisi "d'abord juste
  peupler les champs" ; améliorer le prompt avec `value`/`source` est un
  fast-follow naturel une fois les données en base, mais pas cette
  itération.
- **Script CLI dédié** — évoqué comme piste (réutiliser la même logique que
  `scripts/reset_db.py`), mais pas confirmé par toi ; le module de
  validation reste conçu pour être réutilisable si le besoin se confirme,
  sans construire le script maintenant.
- **Mapping de colonnes configurable** — sur-ingénierie pour un seul fichier
  réel actuellement identifié ; les 8 colonnes de `DATASET GOLD.csv` sont
  codées en dur comme contrat v1.
- **Fusion d'exemples multi-imports** — pas de cas d'usage confirmé
  aujourd'hui ; le remplacement complet par `key` est plus simple et
  prévisible.

## Decisions
- **Migration DB** : `data/app.db` repart de zéro via `scripts/reset_db.py`
  (déjà existant) plutôt qu'une migration des lignes existantes — cohérent
  avec l'absence de données de production réelles.
- **Doublons à l'import** : upsert par `key` en **remplacement complet**
  (pas de fusion) si le `key` existe déjà en base.
- **xlsx obligatoire dès la v1** malgré le coût de dépendance
  (`pandas` + `openpyxl`).
