# Implementation Plan: Traitement PDF + NER réel (Étape 1)

Spec de référence : [specs/pdf-ner-real.md](../specs/pdf-ner-real.md)

## Overview

Remplacer `MockPdfTextExtractor`/`MockNerExtractor` par des implémentations
réelles (PyMuPDF4LLM, LangExtract + Gemini) derrière les `Protocol` existants,
sans toucher `routes/`, `ui/`, ou la signature des `Protocol`. Le grounding
(page + position texte) transite par des champs optionnels sur
`ExtractionResult`, puis est déplacé vers une table SQLite séparée
(`extraction_groundings`) au moment de la persistance. Six tâches
séquentielles (chaque outil dépend du précédent), pas de tranche verticale
UI puisque l'UI/les routes ne changent pas — la "verticale" ici est
outil-par-outil, chacune testable et laissant `uv run pytest` vert.

## Architecture Decisions

- **Marqueur de page natif à PyMuPDF4LLM, pas de sentinelle inventée.**
  `PyMuPDF4LlmTextExtractor.extract_text` reste `(pdf_bytes) -> str` :
  PyMuPDF4LLM sait déjà encoder les sauts de page via son option native
  `page_separators=True`, qui insère `\n\n--- end of page=N ---\n\n` (N
  0-based) après le texte de chaque page — vérifié en Task 3 sur un PDF
  généré en mémoire plutôt que deviné. Pas besoin de sentinelle `\f`
  maison. `LangExtractNerExtractor` retrouvera le numéro de page d'une
  extraction en repérant le dernier séparateur avant l'offset renvoyé par
  LangExtract, puis les retirera avant de construire `text_position`. Ça
  respecte la contrainte "signature Protocol inchangée" de la spec sans
  magie cachée.
- **Moteur de layout GNN désactivé (`pymupdf4llm.use_layout(False)`).**
  PyMuPDF4LLM active par défaut un moteur de mise en page basé modèle (OCR,
  détection de structure) — coûteux et non déterministe, inutile pour de
  simples PDF texte. On force le chemin "rag" classique, plus léger et
  reproductible, cohérent avec "le pipeline doit être le plus simple
  possible" (CLAUDE.md).
- **Le grounding transite par `ExtractionResult`, pas par un canal séparé.**
  `LangExtractNerExtractor.extract` pose `page_number`/`text_position`
  directement sur chaque `ExtractionResult` retourné (champs optionnels,
  `None` pour les mocks). `ExtractionGrounding` (table + modèle) n'existe
  qu'au niveau du repository : construit après l'`INSERT` du résultat, une
  fois son `id` connu, à partir de ces deux champs. Corrige un gap identifié
  en planification (la version précédente de la spec faisait de
  `ExtractionGrounding.result_id` quelque chose que l'extracteur NER aurait dû
  fournir sans jamais connaître cet id) — la spec a été mise à jour en
  conséquence avant ce plan.
- **`ExtractionRunRepository.create_run` passe d'`executemany` à une boucle
  d'inserts individuels.** Nécessaire pour récupérer le `lastrowid` de chaque
  `extraction_results` inséré et y rattacher sa ligne `extraction_groundings`
  (FK). `get_run` fait un `LEFT JOIN` pour repeupler `page_number`/
  `text_position` sur les `ExtractionResult` retournés (`NULL` si absent,
  cohérent avec les runs mock existants).
- **Dataset de test généré en mémoire via `pymupdf`, pas de PDF commité.**
  `pymupdf4llm` dépend déjà de `pymupdf` (`fitz`) en transitif — on l'utilise
  pour construire les 1-2 PDF de test à la volée dans une fixture pytest
  (texte + positions connues), au lieu de committer des binaires PDF. Évite
  d'ajouter une dépendance (reportlab/fpdf2) et respecte le "ne jamais
  committer de PDF" de la spec sans ambiguïté sur ce qui est "factice".

## Dependency Graph

```
Task 1: Dépendances (pymupdf4llm, langextract) + marker pytest `live`
    │
    ▼
Task 2: Schéma extraction_groundings + modèle ExtractionGrounding +
        champs grounding optionnels sur ExtractionResult
    │
    ├──▶ Task 3: PyMuPDF4LlmTextExtractor réel (marqueurs de page) + tests offline
    │
    └──▶ Task 4: Helper de génération de dataset de test (pymupdf, en mémoire)
             │         (parallélisable avec Task 3 — dépend juste de Task 1)
             │
             ▼ (Task 5 dépend de Task 3 ET Task 4)
         Task 5: LangExtractNerExtractor réel (Gemini + grounding) + test opt-in live
             │
             ▼
         Task 6: ExtractionRunRepository — persister/relire le grounding (FK)
             │
             ▼
         Task 7: Injection réelle dans app/main.py (mocks conservés, mode réel par défaut)
    │
    ▼
Task 8: Housekeeping (README, .env.example, success criteria de la spec)
```

**Parallélisable** : Task 3 et Task 4 une fois Task 1/2 posées.

**Séquentiel obligatoire** : Task 1 → Task 2 (schéma avant tout usage),
Task 5 après Task 3 (convention des marqueurs de page) et Task 4 (dataset),
Task 6 après Task 5 (le repository persiste ce que produit l'extracteur réel),
Task 7 en dernier (branchement — rien à câbler tant que 3/5/6 ne sont pas
vérifiés indépendamment).

## Task List

### Phase 1: Foundation

- [ ] Task 1: Dépendances (`pymupdf4llm`, `langextract`) + marker pytest `live`
- [ ] Task 2: Table `extraction_groundings` + modèle `ExtractionGrounding` +
      champs grounding optionnels sur `ExtractionResult`

### Checkpoint: Foundation
- [ ] `uv sync` installe l'environnement sans erreur
- [ ] `uv run pytest` passe intégralement (38/38 existants, aucune régression)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 2: Outils réels

- [x] Task 3: `PyMuPDF4LlmTextExtractor` (texte réel + marqueurs de page) +
      tests unitaires offline
- [x] Task 4: Helper de génération de dataset de test (PDF + valeurs
      attendues, construits en mémoire via `pymupdf`)
- [x] Task 5: `LangExtractNerExtractor` (vrai modèle Gemini + grounding) +
      test opt-in `@pytest.mark.live`

### Checkpoint: Outils réels
- [x] `uv run pytest -m "not live"` passe sans réseau ni clé API (46 passed,
      1 deselected)
- [x] `uv run pytest -m live` passe avec la vraie clé API de l'utilisateur
      (1 passed — vérifié pendant l'implémentation, pas seulement prévu)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 3: Persistance + branchement

- [x] Task 6: `ExtractionRunRepository` — persister/relire le grounding via
      `extraction_groundings` (FK)
- [x] Task 7: `app/main.py` — injection réelle par défaut (mocks conservés,
      disponibles pour les tests existants)

### Checkpoint: Extraction réelle bout-en-bout
- [x] Upload d'un PDF réel dans l'UI → résultat réel affiché avec page +
      citation, persistant après redémarrage du serveur (vérifié via curl
      contre le serveur réel, avec la vraie clé API de l'utilisateur)
- [x] `uv run pytest -m "not live"` passe intégralement (48 passed, 1 deselected)
- [ ] Revue avec l'utilisateur avant de continuer

### Phase 4: Polish

- [ ] Task 8: Housekeeping (README, `.env.example`, cocher les success
      criteria de `specs/pdf-ner-real.md`)

### Checkpoint: Complete
- [ ] Tous les success criteria de `specs/pdf-ner-real.md` sont cochés
- [ ] `uv run pytest -m "not live"` passe intégralement
- [ ] Parcours manuel complet (upload PDF réel → résultat réel avec grounding)
      validé dans le navigateur
- [ ] Revue finale avec l'utilisateur

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| API exacte de PyMuPDF4LLM pour l'accès par page inconnue à ce stade (open question de la spec) | Medium | Vérifier la doc au moment de Task 3 (skill `source-driven-development`) plutôt que deviner ; le marqueur `\f` est une décision de ce plan, indépendante de l'API exacte utilisée pour l'obtenir. |
| API exacte de LangExtract (prompt/examples/format des offsets) inconnue | Medium | Idem, à vérifier au moment de Task 5. |
| Modèle Gemini gratuit par défaut si `LLM_MODEL` vide — nom exact non confirmé | Low | Choisir une valeur par défaut raisonnable à Task 5 et la documenter dans `.env.example` (Task 8) ; pas bloquant pour le reste du plan. |
| Le passage d'`executemany` à des inserts individuels dans `create_run` (Task 6) pourrait régresser les tests existants sur les runs mock | Low | Les tests `test_extraction_repository.py` couvrent déjà `create_run`/`get_run` ; lancer `uv run pytest tests/test_extraction_repository.py -v` immédiatement après Task 6. |
| Test `live` oublié en CI ou lancé par erreur sans clé, cassant une pipeline | Low | Marker `live` explicitement exclu par défaut (Task 1 : `-m "not live"` comme commande de test par défaut dans le README) ; skip conditionnel en plus du marker (défense en profondeur). |

## Open Questions

Aucune bloquante pour démarrer Task 1 — les trois inconnues techniques
(API PyMuPDF4LLM, API LangExtract, modèle Gemini par défaut) sont déjà
identifiées comme Open Questions dans la spec et affectées à des tâches
précises (3, 5, 5) plutôt que bloquant l'ensemble du plan.
