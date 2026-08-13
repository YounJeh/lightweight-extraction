# Spec: Mock UI — Field Management & PDF Extraction (Étape 1, outils simulés)

## Objectif

Construire une application **FastHTML** qui reproduit fidèlement l'UI et les flux de
l'Étape 1 de la roadmap (gestion des champs + upload PDF/NER), avec une **vraie
persistance SQLite**, mais où **les outils externes (PyMuPDF4LLM, LangExtract) sont
entièrement simulés (mock)**. L'objectif n'est pas de livrer le pipeline
d'extraction réel, mais de valider — rapidement et sans dépendance lourde ni appel
LLM — la logique de l'UI, le schéma de données et les routes, avant de brancher les
vrais outils.

**Utilisateur cible :** le développeur du projet (validation interne des flux), pas
encore l'utilisateur final.

**Succès =** on peut lancer l'app, créer/modifier/supprimer des champs, les voir
persister après redémarrage, uploader un PDF, cocher des champs, lancer une
"extraction" simulée et voir un résultat par champ affiché dans l'UI — le tout
couvert par une suite pytest.

## Hypothèses retenues (validées avec l'utilisateur)

1. **PDF → texte : entièrement simulé.** Le PDF uploadé n'est pas réellement
   parsé par PyMuPDF4LLM ; l'app retourne un texte factice fixe quel que soit le
   fichier. On valide seulement le flux d'upload (réception du fichier, stockage
   de ses métadonnées), pas son contenu.
2. **NER : résultats factices fixes.** Le mock LangExtract renvoie, pour chaque
   champ coché, une valeur d'exemple statique (issue des `exemples` du champ ou
   d'un générateur déterministe), **sans grounding/offset réel** dans le texte
   (pas de lien avec la position réelle, puisque le texte lui-même est factice).
3. **Persistance SQLite : champs + résultats d'extraction.** Les champs (titre,
   définition, exemples) **et** les résultats d'extraction (par document, par
   champ) sont persistés en base — un run d'extraction reste consultable après
   coup, pas seulement affiché une fois puis perdu.
4. **PDF non persisté — seules ses métadonnées vivent le temps de la requête.**
   Le fichier PDF uploadé (et ses métadonnées : nom, taille) ne sont conservés
   qu'en mémoire/disque temporaire pendant le traitement de la requête ; rien
   n'est écrit de façon durable sur disque ni en DB pour le fichier lui-même.
   Seul le résultat d'extraction qui en découle est persisté (point 3).
5. **App mono-utilisateur locale.** Pas de mécanisme de session/auth multi-
   utilisateur pour ce mock — un seul utilisateur local à la fois.
6. **Périmètre = Étape 1 uniquement.** Pas de simulation du workflow agentique de
   génération de données (Étape 2) ni de l'entraînement (Étape 3).
7. **Les interfaces des outils sont conçues comme des ports interchangeables**
   (Protocol Python), pour que les implémentations mock puissent être remplacées
   par PyMuPDF4LLM/LangExtract réels sans toucher à l'UI ni à la DB.

## Tech Stack

- Python 3.12
- FastHTML — UI + serveur (routes, composants HTML server-side)
- SQLite (module `sqlite3` standard, pas d'ORM) — persistance des champs et des
  résultats d'extraction (le PDF source lui-même n'est jamais persisté)
- Pydantic — modèles de domaine (`Field`, `ExtractionRun`, `ExtractionResult`)
- pytest + `starlette.testing.TestClient` (ou `httpx`) — tests d'intégration sur
  les routes
- uv — gestion d'environnement et de dépendances
- **Pas de dépendance réelle à PyMuPDF4LLM ni LangExtract dans ce mock** — seules
  des implémentations `Mock*` des interfaces `PdfTextExtractor` / `NerExtractor`
  sont fournies.

## Commands

```
Install : uv sync
Dev     : uv run python -m app.main
Test    : uv run pytest -v
Test+cov: uv run pytest --cov=app --cov-report=term-missing
```

## Project Structure

```
app/
  __init__.py
  main.py              → point d'entrée FastHTML, montage des routes, init DB au démarrage
  db.py                → connexion SQLite, création du schéma (CREATE TABLE IF NOT EXISTS)
  models.py            → modèles Pydantic : Field, FieldCreate, FieldUpdate, ExtractionRun, ExtractionResult
  repository.py        → couche CRUD (FieldRepository) : create/list/get/update/delete
  extraction_repository.py → persistance des runs d'extraction (ExtractionRunRepository) : create_run/list_runs/get_run
  tools/
    __init__.py         → interfaces Protocol : PdfTextExtractor, NerExtractor
    mock_pdf.py          → MockPdfTextExtractor (texte factice fixe)
    mock_ner.py          → MockNerExtractor (valeurs factices par champ)
  routes/
    fields.py            → page + endpoints CRUD des champs (liste déroulante, création, update, delete)
    extraction.py         → page upload PDF + sélection champs + lancement extraction + persistance du run
  ui/
    layout.py             → layout commun + barre latérale (liens vers les 2 pages)
    components.py          → helpers de composants FastHTML réutilisables (formulaire champ, table résultats, etc.)
data/
  .gitkeep               → dossier où vit le fichier SQLite runtime (app.db, gitignored) ; aucun PDF n'y est jamais écrit durablement
tests/
  conftest.py             → fixtures : DB temporaire par test, TestClient FastHTML
  test_field_repository.py → tests unitaires CRUD sur la couche DB (sans HTTP)
  test_fields_routes.py    → tests d'intégration HTTP : créer/lister/modifier/supprimer un champ
  test_extraction_routes.py→ tests d'intégration HTTP : upload PDF + sélection champs + extraction mock + vérification de la persistance du run
  test_extraction_repository.py → tests unitaires CRUD sur les runs d'extraction (sans HTTP)
  test_mock_tools.py       → tests unitaires des simulateurs (déterminisme, forme du résultat)
pyproject.toml
.gitignore                 → doit exclure data/*.db, __pycache__, .venv
specs/
  mock-ui.md               → ce document
CLAUDE.md
README.md
```

## Code Style

Modèles Pydantic explicites, type hints partout, fonctions pures et petites pour
les mocks (pas d'état caché), composants FastHTML sous forme de fonctions
retournant des éléments `FT`.

```python
# app/models.py
from pydantic import BaseModel, Field as PydField

class Field(BaseModel):
    id: int | None = None
    title: str
    definition: str
    examples: list[str] = PydField(default_factory=list)

class ExtractionResult(BaseModel):
    field_title: str
    value: str
    source: str = "mock"  # trace explicite qu'il s'agit d'une simulation

class ExtractionRun(BaseModel):
    id: int | None = None
    document_name: str          # nom du PDF uploadé (métadonnée uniquement, fichier non conservé)
    results: list[ExtractionResult]
```

```python
# app/tools/__init__.py
from typing import Protocol
from app.models import Field, ExtractionResult

class PdfTextExtractor(Protocol):
    def extract_text(self, pdf_bytes: bytes) -> str: ...

class NerExtractor(Protocol):
    def extract(self, text: str, fields: list[Field]) -> list[ExtractionResult]: ...
```

```python
# app/routes/fields.py
from fasthtml.common import *

@rt("/fields")
def get(repo: FieldRepository):
    fields = repo.list_all()
    return Titled("Champs", fields_table(fields), field_form())
```

Conventions : noms de fichiers/modules en `snake_case`, un seul `FieldRepository`
par process (injecté, pas de singleton global mutable en dehors de la connexion
DB), pas de logique métier dans les fonctions de route au-delà de
l'orchestration (validation → repository/tool → rendu).

## Testing Strategy

- Framework : **pytest**, avec `starlette.testing.TestClient` sur l'app FastHTML
  (FastHTML est bâti sur Starlette, le TestClient standard s'applique).
- Isolation DB : chaque test utilise une base SQLite temporaire (fichier
  `tmp_path/test.db` ou `:memory:` selon compatibilité avec la connexion
  utilisée), créée via une fixture `conftest.py` — jamais la DB de dev.
- Niveaux de tests :
  - **Unitaire** — `FieldRepository` (CRUD direct sur DB), `MockPdfTextExtractor`
    et `MockNerExtractor` (déterminisme, forme des résultats).
  - **Intégration** — routes HTTP : CRUD champs via formulaires/endpoints,
    upload PDF (fichier factice en mémoire) + sélection de champs + vérification
    que la réponse contient bien un résultat simulé par champ coché.
- Pas de couverture minimale imposée à ce stade (mock exploratoire), mais chaque
  route et chaque méthode du repository doit avoir au moins un test.
- Aucun appel réseau réel, aucune dépendance à une clé API : tout est mocké par
  construction.

## Boundaries

- **Toujours faire :**
  - Lancer `uv run pytest` avant de considérer une tâche terminée.
  - Garder les outils (PDF, NER) derrière les interfaces `Protocol` définies dans
    `app/tools/__init__.py`, pour permettre un remplacement futur par les vrais
    PyMuPDF4LLM/LangExtract sans changer l'UI ni la DB.
  - Valider les entrées utilisateur (titre de champ non vide, fichier uploadé de
    type PDF) avant écriture en DB ou traitement.
  - Utiliser des requêtes SQLite paramétrées (jamais de concaténation de chaînes
    dans le SQL).
  - Marquer explicitement dans l'UI/les résultats que l'extraction est simulée
    (ex. badge "mock"), pour ne pas créer de confusion avec un vrai résultat NER.

- **Demander avant de faire :**
  - Ajouter une dépendance non listée dans la stack de CLAUDE.md.
  - Modifier le schéma SQLite d'une façon qui casserait la compatibilité avec
    l'Étape 2/3 à venir.
  - Brancher un vrai appel PyMuPDF4LLM ou LangExtract (hors scope explicite de ce
    mock).
  - Ajouter un mécanisme de session/auth multi-utilisateur (hors scope explicite
    de ce mock, mono-utilisateur).

- **Ne jamais faire :**
  - Committer le fichier SQLite de dev (`data/*.db`) ou tout PDF uploadé par un
    utilisateur réel.
  - Écrire le fichier PDF uploadé de façon durable sur disque ou en DB — seules
    ses métadonnées peuvent transiter le temps de la requête, et seul le
    résultat d'extraction qui en découle est persisté.
  - Faire un appel réseau ou LLM réel depuis le code de mock.
  - Supprimer un test qui échoue sans validation explicite de l'utilisateur.

## Success Criteria

- [x] Un champ (titre, définition, exemples) créé via l'UI est persisté en
      SQLite et reste visible après redémarrage du serveur.
      *Vérifié manuellement (curl + redémarrage du serveur, Task 4).*
- [x] La page "Champs" liste tous les champs existants avec leurs attributs, et
      permet update/delete depuis l'UI.
- [x] La page "Extraction" permet d'uploader un PDF, de cocher un sous-ensemble
      des champs disponibles, et de lancer une extraction.
- [x] Le résultat affiché contient une valeur simulée par champ coché, produite
      par `MockNerExtractor`, clairement identifiée comme un résultat mock.
- [x] Le run d'extraction (nom du document + résultats par champ) est persisté
      en SQLite et reste consultable après redémarrage du serveur — le fichier
      PDF source, lui, n'est jamais conservé durablement.
      *Vérifié manuellement (upload → redémarrage → `/extraction/runs/1`
      toujours consultable, Task 9).*
- [x] Aucun appel réseau, aucune lecture réelle du contenu du PDF, aucune
      dépendance à PyMuPDF4LLM/LangExtract réels.
      *`pyproject.toml` ne liste ni PyMuPDF4LLM ni LangExtract.*
- [x] `uv run pytest` passe, avec au moins un test par route et par méthode du
      repository. *38/38 tests passent.*
- [x] Remplacer `MockPdfTextExtractor`/`MockNerExtractor` par une implémentation
      réelle ne nécessite aucune modification des fichiers `routes/`, `ui/`, ou
      `models.py` — uniquement l'injection d'une autre implémentation des
      `Protocol`. *Les deux outils sont injectés dans `create_app()` (app/main.py) ;
      seul ce point d'injection changerait.*

## Open Questions

Aucune question bloquante restante — les trois points précédents ont été
tranchés par l'utilisateur (voir Hypothèses retenues, points 3–5).
