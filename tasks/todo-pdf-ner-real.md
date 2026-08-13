# Task List: Traitement PDF + NER réel (Étape 1)

Plan de référence : [tasks/plan-pdf-ner-real.md](plan-pdf-ner-real.md) · Spec :
[specs/pdf-ner-real.md](../specs/pdf-ner-real.md)

---

## Task 1: Dépendances (`pymupdf4llm`, `langextract`) + marker pytest `live`

**Description:** Ajouter `pymupdf4llm` et `langextract` aux dépendances du
projet, et déclarer un marker pytest `live` (dans `pyproject.toml`,
`[tool.pytest.ini_options]`) pour les tests qui appellent le vrai modèle
Gemini. La commande de test par défaut du README passe à
`uv run pytest -m "not live"`.

**Acceptance criteria:**
- [ ] `uv sync` installe `pymupdf4llm` et `langextract` sans erreur
- [ ] `uv run pytest --markers` liste le marker `live`
- [ ] `uv run pytest -v` (sans filtre) continue de passer intégralement (rien
      n'utilise encore les nouvelles dépendances)

**Verification:**
- [ ] Tests: `uv run pytest -v`
- [ ] Build: `uv sync`

**Dependencies:** None

**Files likely touched:**
- `pyproject.toml`
- `uv.lock`

**Estimated scope:** XS (1 fichier de config + lock)

---

## Task 2: Table `extraction_groundings` + modèle `ExtractionGrounding` + champs grounding sur `ExtractionResult`

**Description:** Ajouter la table `extraction_groundings` au schéma SQLite
(`app/db.py`, `CREATE TABLE IF NOT EXISTS`, FK vers `extraction_results.id`),
le modèle Pydantic `ExtractionGrounding` (concept interne au repository :
`result_id`, `page_number`, `text_position`), et deux champs optionnels
(`page_number: int | None`, `text_position: str | None`) sur `ExtractionResult`
existant — c'est par ces deux champs que le grounding transite depuis
l'extracteur NER avant d'être déplacé vers la table séparée par le
repository (Task 6).

**Acceptance criteria:**
- [ ] Le schéma crée `extraction_groundings` sans erreur sur une base vide,
      avec FK vers `extraction_results(id)`
- [ ] `ExtractionResult(field_title=..., value=...)` reste valide sans
      grounding (champs par défaut `None`) — aucune régression sur les mocks
- [ ] `ExtractionGrounding` valide `result_id`/`page_number`/`text_position`
      comme requis (pas de sens sans ces trois valeurs)

**Verification:**
- [ ] Tests: `uv run pytest -v tests/test_db.py` (schéma) et tests modèles
      existants (aucune régression sur `ExtractionResult`)

**Dependencies:** Task 1

**Files likely touched:**
- `app/db.py`
- `app/models.py`
- `tests/test_db.py`

**Estimated scope:** S (2 fichiers)

---

## Checkpoint: Foundation (après Tasks 1-2)
- [ ] `uv sync` installe l'environnement sans erreur
- [ ] `uv run pytest` passe intégralement (38/38 existants, aucune régression)
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 3: `PyMuPDF4LlmTextExtractor` réel (texte + marqueurs de page)

**Description:** Implémenter `PyMuPDF4LlmTextExtractor(PdfTextExtractor)`
dans `app/tools/pdf_pymupdf4llm.py` : extrait le texte réel d'un PDF avec
`pymupdf4llm.to_markdown(doc, page_separators=True)` (moteur layout désactivé
via `pymupdf4llm.use_layout(False)`, voir Architecture Decisions du plan) —
`extract_text` reste `(pdf_bytes: bytes) -> str`, aucune modification du
`Protocol`. Les séparateurs de page (`--- end of page=N ---`) sont natifs à
la lib, vérifiés par un appel réel plutôt que devinés.

**Acceptance criteria:**
- [ ] `extract_text` sur un PDF réel multi-page retourne le texte réel de
      chaque page, chacune terminée par un marqueur `--- end of page=N ---`
      (N 0-based)
- [ ] Sur un PDF d'une seule page, le marqueur de fin de page est bien
      présent (comportement natif de la lib, pas de cas particulier à gérer)
- [ ] Ne dépend d'aucune clé API (parsing PDF pur, pas d'appel réseau)

**Verification:**
- [ ] Tests: `uv run pytest -v tests/test_pdf_pymupdf4llm.py` — PDF de test
      généré en mémoire via `pymupdf` (pas de fichier binaire commité)

**Dependencies:** Task 1 (dépendance installée)

**Files likely touched:**
- `app/tools/pdf_pymupdf4llm.py`
- `tests/test_pdf_pymupdf4llm.py`

**Estimated scope:** S (2 fichiers)

---

## Task 4: Helper de génération de dataset de test

**Description:** Écrire un helper de test (`tests/pdf_fixtures.py` ou
équivalent) qui construit en mémoire, via `pymupdf`, 1-2 PDF simples avec un
texte connu et des valeurs attendues pour 2-3 champs — réutilisé par le test
offline de Task 3 (relecture) et surtout par le test live de Task 5. Pas de
PDF committé dans le dépôt : le générateur est la source de vérité.

**Acceptance criteria:**
- [ ] Le helper produit des `bytes` PDF valides (relisibles par
      `PyMuPDF4LlmTextExtractor`) et un mapping champ → valeur attendue
- [ ] Déterministe **au niveau du texte extrait** (le PDF brut généré par
      `pymupdf` n'est pas byte-identique d'un appel à l'autre — métadonnées
      d'horodatage internes — mais `PyMuPDF4LlmTextExtractor.extract_text`
      dessus retourne toujours le même texte)
- [ ] Aucune dépendance nouvelle (réutilise `pymupdf`, déjà tiré par
      `pymupdf4llm`)

**Verification:**
- [ ] Tests: un test dédié vérifie que le PDF généré est bien parsable par
      `PyMuPDF4LlmTextExtractor` et contient le texte attendu

**Dependencies:** Task 1 (parallélisable avec Task 3)

**Files likely touched:**
- `tests/pdf_fixtures.py`
- `tests/test_pdf_fixtures.py` (ou test intégré au fichier ci-dessus)

**Estimated scope:** S (1-2 fichiers)

---

## Task 5: `LangExtractNerExtractor` réel (Gemini + grounding) + test opt-in

**Description:** Implémenter `LangExtractNerExtractor(NerExtractor)` dans
`app/tools/ner_langextract.py` : appelle le vrai modèle Gemini via LangExtract
(clé et modèle lus depuis `.env` — `GOOGLE_GENERATIVE_AI_API_KEY`,
`LLM_MODEL`, avec une valeur par défaut documentée si `LLM_MODEL` est vide),
mappe les offsets/citations renvoyés par LangExtract vers `page_number`
(comptage des marqueurs `\f` avant l'offset) et `text_position` sur chaque
`ExtractionResult`. Vérifier l'API exacte de LangExtract (skill
`source-driven-development`) plutôt que deviner. Ajoute
`tests/test_ner_langextract_live.py`, marqué `@pytest.mark.live` et skip si
`GOOGLE_GENERATIVE_AI_API_KEY` absent de l'environnement.

**Acceptance criteria:**
- [x] Sur le dataset de Task 4, extrait les valeurs attendues pour les champs
      de test via un vrai appel Gemini
- [x] Chaque `ExtractionResult` retourné porte `page_number` et
      `text_position` cohérents avec le PDF source (marqueurs de Task 3
      correctement décodés)
- [x] `source="langextract"` sur les résultats réels (vs `"mock"`)
- [x] Le test live est skip (pas fail) quand la clé API est absente

**Verification:**
- [x] Tests: `uv run pytest -v -m "not live"` (46 passed, 1 deselected) ;
      `uv run pytest -v -m live` exécuté avec la vraie clé de l'utilisateur
      (1 passed, voir note ci-dessous)

**Dependencies:** Task 2 (champs grounding sur `ExtractionResult`), Task 3
(convention des marqueurs de page), Task 4 (dataset de test)

**Files likely touched:**
- `app/tools/ner_langextract.py`
- `tests/test_ner_langextract_live.py`
- `app/config.py` *(ajouté — voir note ci-dessous)*
- `tests/conftest.py` *(idem)*

**Note découverte à l'implémentation :** rien ne chargeait `.env` dans
`os.environ` (pas de `python-dotenv`, pas de parsing maison) — sans ça,
`os.getenv("GOOGLE_GENERATIVE_AI_API_KEY")` renvoie toujours `None`, y
compris pour le skip du test live. Ajouté `app/config.py::load_env()` (parseur
`.env` minimal, sans nouvelle dépendance) appelé depuis `tests/conftest.py`.
Task 7 devra l'appeler aussi depuis `app/main.py` pour que l'app elle-même
lise `.env` au démarrage. `LLM_MODEL` dans `.env`/`.env.example` a aussi été
corrigé : la valeur `google/gemini-3.6-flash` saisie manuellement ne
correspond pas au format attendu par LangExtract (pas de préfixe fournisseur)
ni à un modèle connu ; remise à vide pour utiliser le défaut LangExtract
vérifié (`gemini-3.5-flash`, confirmé par une lecture directe de la lib
installée puis par un appel réel réussi).

**Vérifié en live** (avec la vraie clé de l'utilisateur, hors CI) :
`uv run pytest -v -m live` → 1 passed — extraction réelle des 3 valeurs
connues du dataset Task 4, avec `page_number`/`text_position` cohérents.

**Estimated scope:** M (2 fichiers, logique de mapping non triviale) — révisé
à L une fois le chargement `.env` inclus, toujours dans un seul incrément
cohérent (le test live ne peut pas être vérifié sans lui).

---

## Checkpoint: Outils réels (après Tasks 3-5)
- [ ] `uv run pytest -m "not live"` passe sans réseau ni clé API
- [ ] `uv run pytest -m live` passe manuellement avec une vraie clé API
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 6: `ExtractionRunRepository` — persister/relire le grounding

**Description:** Faire évoluer `create_run` (actuellement `executemany`) vers
des inserts individuels dans `extraction_results`, afin de récupérer le
`lastrowid` de chaque résultat et y rattacher une ligne
`extraction_groundings` quand `page_number`/`text_position` sont présents sur
le `ExtractionResult` source. `get_run`/`list_runs` font un `LEFT JOIN` vers
`extraction_groundings` pour repeupler ces deux champs sur les
`ExtractionResult` retournés (`None` si absent — cas des runs mock).

**Acceptance criteria:**
- [ ] Un run créé avec des résultats ayant du grounding le conserve après
      `get_run` (page + position identiques à l'entrée)
- [ ] Un run créé avec des résultats mock (sans grounding) fonctionne comme
      aujourd'hui — pas de régression
- [ ] Requêtes SQL paramétrées uniquement

**Verification:**
- [ ] Tests: `uv run pytest -v tests/test_extraction_repository.py` (cas
      avec et sans grounding)

**Dependencies:** Task 2 (schéma), Task 5 (forme des `ExtractionResult` à
persister)

**Files likely touched:**
- `app/extraction_repository.py`
- `tests/test_extraction_repository.py`

**Estimated scope:** S (2 fichiers)

---

## Task 7: Injection réelle dans `app/main.py`

**Description:** Remplacer l'injection par défaut de `MockPdfTextExtractor`/
`MockNerExtractor` par `PyMuPDF4LlmTextExtractor`/`LangExtractNerExtractor`
dans `app/main.py` (point d'injection unique, comme documenté dans
`specs/mock-ui.md`). Les mocks restent dans le code (non supprimés) pour les
tests de routes existants (`test_extraction_routes.py`), qui continuent à les
injecter explicitement.

**Acceptance criteria:**
- [ ] `uv run python -m app.main` démarre avec les outils réels par défaut
- [ ] Aucune modification de `app/routes/extraction.py`, `app/ui/`, ou des
      signatures des `Protocol`
- [ ] Upload d'un PDF réel via l'UI → résultat réel affiché avec badge
      `langextract` (pas `mock`), page + citation visibles

**Verification:**
- [ ] Tests: `uv run pytest -v -m "not live"` (aucune régression sur les
      tests de routes, qui utilisent toujours les mocks explicitement)
- [ ] Manuel: upload d'un PDF réel via le navigateur (ou curl contre le
      serveur réel), avec une vraie clé API dans `.env`, redémarrage du
      serveur pour vérifier la persistance du run

**Dependencies:** Task 3, Task 5, Task 6

**Files likely touched:**
- `app/main.py`

**Estimated scope:** XS (1 fichier)

---

## Checkpoint: Extraction réelle bout-en-bout (après Task 7)
- [ ] Upload d'un PDF réel dans l'UI → résultat réel avec page + citation,
      persistant après redémarrage du serveur
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Revue avec l'utilisateur avant de continuer

---

## Task 8: Housekeeping (README, `.env.example`, success criteria)

**Description:** Documenter la commande de test live dans le README
(`uv run pytest -m live`, prérequis `.env` avec clé API), compléter
`.env.example` avec un commentaire sur le modèle Gemini par défaut retenu à
Task 5, et repasser explicitement chaque success criterion de
`specs/pdf-ner-real.md` pour cocher ce qui est fait.

**Acceptance criteria:**
- [ ] `README.md` documente `uv run pytest -m "not live"` (défaut) et
      `uv run pytest -m live` (opt-in, nécessite clé API)
- [ ] `.env.example` documente le modèle par défaut si `LLM_MODEL` est vide
- [ ] Tous les success criteria de la spec sont cochés ou justifiés

**Verification:**
- [ ] Tests: `uv run pytest -m "not live"` (aucune régression)
- [ ] Manuel: relecture croisée `specs/pdf-ner-real.md` § Success Criteria
      vs état réel de l'app

**Dependencies:** Task 7

**Files likely touched:**
- `README.md`
- `.env.example`
- `specs/pdf-ner-real.md` (cocher les success criteria)

**Estimated scope:** XS (3 fichiers, pas de nouveau code applicatif)

---

## Checkpoint: Complete (après Task 8)
- [ ] Tous les success criteria de `specs/pdf-ner-real.md` sont cochés
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Parcours manuel complet (upload PDF réel → résultat réel avec
      grounding) validé
- [ ] Revue finale avec l'utilisateur
