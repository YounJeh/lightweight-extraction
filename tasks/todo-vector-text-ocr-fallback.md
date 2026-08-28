# Task List: Fix du filtre `_AREA_SKIP_THRESHOLD` (texte vectorisé bloqué à tort)

Plan de référence : [tasks/plan-vector-text-ocr-fallback.md](plan-vector-text-ocr-fallback.md)

Plan précédent (second passage OCR ciblé) abandonné après spike sur le vrai
fichier : la cause réelle est plus simple qu'anticipé, voir le plan pour le
détail.

---

## Task 1: Corriger la condition de skip dans `_tracking_ocr_function` ✅

**Description:** Dans `app/tools/pdf_pymupdf4llm.py::PyMuPDF4LlmTextExtractor._tracking_ocr_function`,
la fonction `wrapped` skip l'OCR uniquement sur la base de `img_area`. Ajouter
`vec_norects` (déjà disponible dans le dict retourné par `analyze_page`) à la
condition, pour ne skip que si la page n'a ni image significative ni vecteurs
suspects.

**Acceptance criteria:**
- [ ] `if area < _AREA_SKIP_THRESHOLD: return None` devient
      `if area < _AREA_SKIP_THRESHOLD and not vec_norects: return None`.
- [ ] Le commentaire de `_AREA_SKIP_THRESHOLD` (l. 39-45) reflète la nouvelle
      condition (mentionne explicitement que le skip ne s'applique que si
      `vec_norects` est aussi nul — sinon une page à texte vectorisé sans
      image significative ne serait jamais OCRisée).

**Verification:**
- [ ] `uv run pytest -m "not live"` passe.
- [ ] Manuel : sur `data_test/Devis n°63505 - ENTECH - PDL - Poste D_24_1224_IMPL_1000 - Département 01_DDN.pdf`,
      `last_pages_ocr == [1, 2, 3, 4]` et le contenu des pages 2/3/4 dépasse
      largement 42/20/0 caractères.

**Dependencies:** None

**Files likely touched:**
- `app/tools/pdf_pymupdf4llm.py`

**Estimated scope:** XS

---

## Task 2: Test de non-régression (garde-fou) ✅

**Description:** Ajouter un test unitaire dans `tests/test_pdf_pymupdf4llm.py`
qui reproduit le cas (page avec `img_area` sous le seuil mais `vec_norects`
significatif) et vérifie que l'OCR est bien déclenché sur cette page — sans
dépendre du fichier réel (mock/fixture minimal). Doit échouer sans le fix et
passer avec.

**Acceptance criteria:**
- [ ] Le test échoue si on revient à l'ancienne condition (`area < threshold`
      seule).
- [ ] Le test ne dépend pas du fichier `data_test/Devis n°63505...` (pas
      committé dans les fixtures de test, potentiellement confidentiel).
- [ ] Convention de test existante du fichier respectée (mocks/fixtures déjà
      en place pour `PyMuPDF4LlmTextExtractor`, à vérifier avant d'écrire).

**Verification:**
- [ ] `uv run pytest -m "not live"` passe, le nouveau test est bien exécuté.

**Dependencies:** Task 1

**Files likely touched:**
- `tests/test_pdf_pymupdf4llm.py`

**Estimated scope:** S

---

## Task 3: Vérification manuelle bout-en-bout sur le fichier réel ✅

**Description:** Confirmer sur le vrai fichier que le fix résout le problème
initialement rapporté par l'utilisateur (pages 3-4 quasi vides), et que la
page 1 (déjà correcte) n'est pas dégradée.

**Acceptance criteria:**
- [ ] `last_pages_ocr == [1, 2, 3, 4]` sur le fichier réel.
- [ ] Contenu des pages 2/3/4 cohérent avec le test du spike (~2873/1356/1399
      caractères, tableau technique et conditions de paiement lisibles).
- [ ] Page 1 inchangée (~2343 caractères).

**Verification:**
- [ ] Script ponctuel ou test manuel via `PyMuPDF4LlmTextExtractor.extract_text`
      sur le fichier réel.

**Dependencies:** Task 1

**Files likely touched:** aucun (vérification uniquement)

**Estimated scope:** XS

---

## Checkpoint: Complete

- [x] `uv run pytest -m "not live"` passe intégralement (218 passed)
- [x] Manuel : pages 2/3/4 du fichier réel remontent le contenu attendu
      (2873/1356/1399 caractères, vs 42/20/0 avant)
- [ ] Non-régression corpus gold — **laissée à l'utilisateur**
      (`scripts/validate_ocr_tuning.py`, pas exécuté dans ce lot)
- [ ] Revue avec l'utilisateur → proposer `/code-review-and-quality` puis la
      PR (règle CLAUDE.md)
