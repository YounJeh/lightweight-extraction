# Spec: Traitement PDF + NER réel (Étape 1)

## Objectif

Remplacer les implémentations mock (`MockPdfTextExtractor`, `MockNerExtractor`,
voir [specs/mock-ui.md](mock-ui.md)) par un pipeline réel : parsing PDF avec
**PyMuPDF4LLM**, extraction NER avec **LangExtract** sur un modèle **Gemini
gratuit**, résultats enrichis d'un grounding textuel (page + position dans le
texte source). L'UI, les routes, le schéma de persistance des champs et la
structure des runs restent inchangés — seuls les outils derrière les
`Protocol` existants (`app/tools/__init__.py`) et le modèle `ExtractionResult`
évoluent.

**Utilisateur cible :** le développeur du projet — valider que le pipeline
réel fonctionne sur un vrai PDF, pas encore l'utilisateur final packagé.

**Succès =** uploader un PDF réel, cocher des champs, obtenir des valeurs
extraites par le vrai modèle Gemini via LangExtract, chacune associée à une
page et une position/citation dans le texte source, persistées comme
aujourd'hui — vérifié par un test pytest opt-in (vrai appel API) et par une
inspection manuelle sur un PDF réel.

## Hypothèses retenues (validées avec l'utilisateur via `/idea-refine`)

1. **Grounding = page + position/citation dans le texte extrait**, pas de
   bounding box (coordonnées pixel) à cette étape.
2. **Le `Protocol` `NerExtractor` actuel est conservé tel quel**
   (`extract(text, fields) -> list[ExtractionResult]`) ; `LangExtractNerExtractor`
   l'implémente en interne (prompt, few-shot examples LangExtract gérés côté
   adaptateur, pas exposés dans le contrat ni dans `Field`).
3. **Dataset de test réel = test pytest opt-in**, skip automatique si aucune
   clé API n'est présente dans l'environnement — pas de script séparé hors
   suite de tests.
4. **Périmètre = Étape 1 uniquement.** Pas de surlignage visuel du PDF dans
   l'UI (nécessiterait le bounding box exclu au point 1).
5. **Grounding = table SQLite séparée**, pas de colonnes ajoutées sur
   `extraction_results`. Une table dédiée (ex. `extraction_groundings`,
   liée par clé étrangère au résultat) porte `page_number`/`text_position`,
   pour garder `extraction_results` compatible avec les runs mock existants
   (qui n'ont pas de grounding) sans colonnes nullable partout.

## Tech Stack

- Python 3.12 (inchangé)
- **PyMuPDF4LLM** — parsing PDF → texte, avec accès par page (nécessaire pour
  reconstituer le numéro de page du grounding)
- **LangExtract** — extraction NER + grounding textuel natif (offsets/citation
  dans le texte fourni), orchestrant l'appel au modèle Gemini
- SDK Gemini utilisé par LangExtract — clé lue depuis `.env`
  (`GOOGLE_GENERATIVE_AI_API_KEY`, modèle via `LLM_MODEL`)
- Reste de la stack inchangé : FastHTML, SQLite (`sqlite3` standard),
  Pydantic, pytest, uv

## Commands

```
Install : uv sync
Dev     : uv run python -m app.main
Test    : uv run pytest -v
Test réel (opt-in, nécessite .env avec GOOGLE_GENERATIVE_AI_API_KEY) :
          uv run pytest -v -m live
```

## Project Structure

```
app/
  tools/
    __init__.py              → Protocol inchangés (PdfTextExtractor, NerExtractor)
    mock_pdf.py               → conservé (utile pour les tests routes existants)
    mock_ner.py                → conservé (idem)
    pdf_pymupdf4llm.py          → PyMuPDF4LlmTextExtractor(PdfTextExtractor) — implémentation réelle
    ner_langextract.py           → LangExtractNerExtractor(NerExtractor) — implémentation réelle
  models.py                     → nouveau modèle ExtractionGrounding (page, position/citation)
  db.py                          → nouvelle table extraction_groundings (FK vers extraction_results)
  main.py                       → point d'injection à changer (mock → réel), lecture .env
data/
  test_pdfs/                    → petit dataset de test (1-2 PDF factices simples + valeurs attendues connues)
tests/
  test_pdf_pymupdf4llm.py       → tests unitaires offline (PDF local, pas de réseau)
  test_ner_langextract_live.py  → test opt-in, vrai appel Gemini, marqué `@pytest.mark.live`
.env / .env.example             → déjà en place (GOOGLE_GENERATIVE_AI_API_KEY, LLM_MODEL)
specs/
  pdf-ner-real.md                → ce document
```

## Code Style

```python
# app/models.py — ExtractionResult reste le seul canal de sortie de l'outil
# (Protocol NerExtractor inchangé) ; le grounding y transite en optionnel.
class ExtractionResult(BaseModel):
    field_title: str
    value: str
    source: str = "mock"              # "mock" | "langextract"
    page_number: int | None = None    # None si non applicable (ex. mock)
    text_position: str | None = None  # citation/extrait du texte source

# Forme de la ligne SQLite dans la table séparée extraction_groundings —
# concept interne au repository, jamais manipulé par l'extracteur NER
# (le repository la construit après l'INSERT du ExtractionResult, une fois
# son id connu, à partir de result.page_number/result.text_position).
class ExtractionGrounding(BaseModel):
    result_id: int             # FK vers extraction_results.id
    page_number: int
    text_position: str
```

```python
# app/tools/ner_langextract.py — respecte le Protocol existant sans l'étendre
class LangExtractNerExtractor:
    def extract(self, text: str, fields: list[Field]) -> list[ExtractionResult]:
        ...  # traduit fields -> prompt/examples LangExtract ; le grounding
             # (page, char offsets) renvoyé par LangExtract est posé
             # directement sur page_number/text_position de chaque
             # ExtractionResult — le repository se charge de le déplacer
             # vers extraction_groundings au moment de la persistance
```

```python
# tests/test_ner_langextract_live.py
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("GOOGLE_GENERATIVE_AI_API_KEY"),
    reason="nécessite une vraie clé API Gemini",
)
```

Conventions inchangées par rapport à `specs/mock-ui.md` (snake_case, pas de
logique métier dans les routes, requêtes SQL paramétrées).

## Testing Strategy

- **Unitaire, offline** : `PyMuPDF4LlmTextExtractor` sur un PDF local fixe du
  dépôt (pas d'appel réseau) — vérifie que le texte extrait correspond au
  contenu réel du PDF et que le découpage par page est exploitable.
- **Intégration, opt-in (`@pytest.mark.live`)** : `LangExtractNerExtractor`
  appelle le vrai modèle Gemini sur 1-2 PDF du dataset `data/test_pdfs/` avec
  des champs et valeurs attendues connus à l'avance. Skip automatique si
  `GOOGLE_GENERATIVE_AI_API_KEY` est absent de l'environnement — n'exécute
  jamais par défaut dans `uv run pytest` sans configuration explicite.
- **Manuel** : upload d'un PDF réel via l'UI existante, inspection du résultat
  affiché (valeur + page + position) une fois le pipeline réel branché.
- Les tests existants sur les mocks (`test_mock_tools.py`,
  `test_extraction_routes.py`) restent inchangés et continuent de tourner sans
  réseau.

## Boundaries

- **Toujours faire :**
  - Garder la signature des `Protocol` `PdfTextExtractor`/`NerExtractor`
    inchangée — toute info de grounding supplémentaire passe par
    `ExtractionResult`, pas par le contrat de l'outil.
  - Marquer tout test qui appelle le vrai modèle Gemini avec
    `@pytest.mark.live` (ou équivalent skip conditionnel) — jamais d'appel
    réseau dans `uv run pytest` par défaut.
  - Lire la clé API et le nom du modèle uniquement depuis `.env`
    (`GOOGLE_GENERATIVE_AI_API_KEY`, `LLM_MODEL`), jamais en dur dans le code.
  - Conserver les mocks existants (ne pas les supprimer) — ils restent la
    voie de test rapide pour l'UI/les routes.

- **Demander avant de faire :**
  - Ajouter une dépendance Python non listée dans la stack de CLAUDE.md
    (PyMuPDF4LLM et LangExtract sont pré-approuvés ; tout autre SDK/lib
    nécessite validation).
  - Choisir un modèle Gemini par défaut si `LLM_MODEL` est vide dans `.env`.

- **Ne jamais faire :**
  - Committer une clé API réelle (déjà couvert par `.gitignore` : `.env`).
  - Committer un PDF réel/sensible dans `data/test_pdfs/` — seuls des PDF
    factices minimalistes créés pour le test sont acceptés.
  - Faire dépendre le comportement par défaut de l'app (démarrage, tests
    standards) de la présence d'une clé API.

## Success Criteria

- [x] `PyMuPDF4LlmTextExtractor` remplace le mock et extrait le texte réel
      d'un PDF uploadé, avec accès par page.
      *Marqueurs de page natifs à PyMuPDF4LLM (`page_separators=True`),
      vérifié sur un PDF réel multi-page (Task 3).*
- [x] `LangExtractNerExtractor` appelle le vrai modèle Gemini (configuré via
      `.env`) pour extraire les valeurs des champs sélectionnés.
      *Vérifié avec un vrai appel API (Task 5, `pytest -m live`).*
- [x] Chaque `ExtractionResult` réel a un `ExtractionGrounding` associé
      (`page_number` + `text_position`), persisté dans la table séparée
      `extraction_groundings`.
      *Round-trip vérifié via `ExtractionRunRepository` (Task 6).*
- [x] Le modèle Gemini utilisé est configurable via `LLM_MODEL` dans `.env`,
      avec un comportement défini si la variable est vide.
      *Vide → défaut LangExtract natif (`gemini-3.5-flash`), pas de valeur
      dupliquée en dur côté app (Task 5).*
- [x] Un test pytest opt-in (`@pytest.mark.live`, skip sans clé API) vérifie
      l'extraction réelle sur un petit dataset contre des valeurs attendues
      connues.
      *Dataset généré en mémoire via `pymupdf` (`tests/pdf_fixtures.py`) plutôt
      que des fichiers dans `data/test_pdfs/` — décision prise en Task 4 pour
      éviter de committer des binaires (voir Architecture Decisions du plan).*
- [x] Vérification manuelle : upload d'un PDF réel via l'UI, résultat
      correctement extrait et affiché avec page + position.
      *Vérifié via curl contre le serveur réel (Task 7) : badge `langextract`,
      page + citation affichés, run persistant après redémarrage.*
- [x] Aucune modification de `app/routes/`, ou des signatures des
      `Protocol` — uniquement nouvelles implémentations d'outils + point
      d'injection dans `app/main.py` + enrichissement de `ExtractionResult`.
      *Exception découverte et documentée en Task 7 : `app/ui/components.py`
      a nécessité deux petites modifications (badge dynamique au lieu de
      `"mock"` en dur, affichage du grounding) — sans elles ce critère de
      succès lui-même (badge/page/position visibles) n'était pas atteignable.*
- [x] `uv run pytest` (sans le marqueur `live`) passe toujours sans réseau ni
      clé API.
      *48 passed, 1 deselected.*

## Open Questions

Toutes résolues à l'implémentation (voir `tasks/plan-pdf-ner-real.md` pour le
détail) :
- API PyMuPDF4LLM pour l'accès par page → `page_separators=True` (marqueurs
  natifs `--- end of page=N ---`, moteur layout désactivé via `use_layout(False)`).
- API LangExtract → `langextract.extract(...)` + `data.ExampleData`/
  `Extraction`/`CharInterval` pour les offsets.
- Modèle Gemini par défaut → aucune valeur en dur ; `LLM_MODEL` vide laisse
  LangExtract appliquer son propre défaut (`gemini-3.5-flash` au moment de
  l'implémentation).
