# Implementation Plan: Fix du filtre `_AREA_SKIP_THRESHOLD` (texte vectorisé bloqué à tort)

Contexte : issu d'une session `/debugging-and-error-recovery` sur le fichier
« Devis n°63505 - ENTECH - PDL - Poste D_24_1224_IMPL_1000 - Département
01_DDN.pdf » (désormais dans `data_test/`) — pages 2 à 4 quasi vides à
l'extraction (42 / 20 / 0 caractères) alors qu'elles contiennent un tableau
technique avec des données utiles (transport, grutage, conditions de
paiement...). Confirmé par l'utilisateur : le texte n'est pas copiable dans
une visionneuse PDF → **texte vectorisé** (converti en courbes/contours à
l'export CAO), pas un scan raster.

## Root cause (révisée après test sur le vrai fichier)

**Hypothèse initiale invalidée** : on pensait que PyMuPDF4LLM lui-même ne
détectait pas le besoin d'OCR sur ces pages (cas `only_text` : ni image ni
vecteur suspect). Test empirique sur le vrai fichier via
`pymupdf4llm.helpers.utils.analyze_page()` :

| Page | `img_area` | `vec_norects` | `needs_ocr` (interne) | `probability` |
|---|---|---|---|---|
| 1 | 0.174 | 1282 | True | 0.99 |
| 2 | 0.027 | 1714 | True | 0.99 |
| 3 | 0.027 | 705 | True | 0.99 |
| 4 | 0.027 | 725 | True | 0.99 |

PyMuPDF4LLM détecte **correctement** le besoin d'OCR sur les 4 pages
(`vec_norects` énorme = signature du texte vectorisé). Le vrai coupable est
notre propre filtre dans `_tracking_ocr_function`
([app/tools/pdf_pymupdf4llm.py](../app/tools/pdf_pymupdf4llm.py), l. 127-132) :

```python
area = pymupdf4llm_utils.analyze_page(page).get("img_area", 0)
if area < _AREA_SKIP_THRESHOLD:   # 0.05
    return None                   # bloque l'OCR même si vec_norects est énorme
```

Sur les pages 2-4, `img_area` (0.027, probablement un petit logo d'en-tête)
tombe sous le seuil de 0.05 — pensé à l'origine pour ignorer les logos
isolés (voir commentaire l. 39-45) — et notre filtre écrase la décision
correcte de PyMuPDF4LLM, qui elle se basait sur `vec_norects`, pas sur
`img_area`.

## Overview

Fix ciblé d'une ligne : ne skip l'OCR par aire d'image que si la page n'a
**ni** image significative **ni** vecteurs suspects (`vec_norects`). Testé
empiriquement sur le vrai fichier :

```python
if area < _AREA_SKIP_THRESHOLD and not vec_norects:
    return None
```

→ `pages_ocr` passe de `[1]` à `[1, 2, 3, 4]`, contenu extrait des pages 2/3/4
passe de 42/20/0 à 2873/1356/1399 caractères.

Le plan précédent (second passage OCR ciblé, détection par comptage de
caractères, spike `force_ocr`) est **abandonné** : inutile, la décision
interne de PyMuPDF4LLM était déjà correcte, seul notre filtre la bloquait.

## Task List

- [x] Task 1: Corriger la condition de skip dans `_tracking_ocr_function`
      (ajout du garde-fou `vec_norects`)
- [x] Task 2: Test de non-régression (garde-fou) reproduisant le cas
- [x] Task 3: Vérification manuelle bout-en-bout sur le fichier réel

### Checkpoint: Complete
- [x] `uv run pytest -m "not live"` passe intégralement (218 passed)
- [x] Manuel : pages 2/3/4 du fichier réel remontent le contenu attendu
      (2873/1356/1399 caractères, vs 42/20/0 avant)
- [ ] Non-régression corpus gold — **laissée à l'utilisateur**, pas exécutée
      dans ce lot (`scripts/validate_ocr_tuning.py`)
- [x] `choix_techniques.md` mis à jour (section "Latence OCR", paragraphe
      "Correctif (texte vectorisé)")
- [ ] Revue avec l'utilisateur → proposer `/code-review-and-quality` puis la
      PR (règle CLAUDE.md)

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Le garde-fou `vec_norects` peut déclencher l'OCR sur des pages qui n'en ont pas vraiment besoin (faux positif : vecteurs nombreux mais pas du texte vectorisé, ex. un schéma/logo complexe) | Medium | Non validé sur le corpus gold dans ce lot (l'utilisateur le fera lui-même) — documenté comme risque ouvert, pas de régression connue à ce stade sur les 4 pages testées. |
| `_AREA_SKIP_THRESHOLD` avait été validé (60% plus rapide, 0 régression) sur un corpus qui ne contenait apparemment aucun cas de texte vectorisé — la validation existante ne couvre pas ce nouveau chemin | Low | Le changement est strictement plus permissif (déclenche l'OCR dans plus de cas, jamais moins) — au pire un léger surcoût de latence sur des pages auparavant skippées à tort, pas de perte de contenu. |

## Open Questions

- Aucune bloquante restante — le fix est validé empiriquement sur le fichier
  réel. Seule la validation du corpus gold (non bloquante, faite séparément
  par l'utilisateur) reste ouverte.
