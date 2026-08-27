# CI d'évaluation du pipeline sur le dataset gold

## Problem Statement
Comment rejouer le workflow d'extraction complet (PDF → NER) sur le dataset gold versionné, à la demande, en traçant temps d'exécution, coût, précision, F1 et métriques d'extraction structurée par run — comparables dans le temps, entièrement dans Langfuse ?

## Recommended Direction

Un script CI qui : (1) synchronise `tests/data/dataset_gold_devis.yaml` vers un **Dataset Langfuse** (`gold-devis`), un item par `document_id` ; (2) rejoue **le pipeline de production réel** (`PyMuPDF4LlmTextExtractor` → `LangExtractNerExtractor`, avec le `LangfuseTracer` déjà en place) sur chaque item via `dataset.run_experiment(...)` ; (3) attache des scores Langfuse item-level (précision/recall/F1 par champ, exact-match document, latence, coût) et run-level (agrégats macro) sur le run résultant.

Ce choix évite toute réimplémentation du pipeline pour l'éval (risque classique de "skew" éval/prod) et élimine le besoin d'un outil de versioning séparé (MLflow, évoqué dans `notes.md` comme "si gratuit") : Langfuse Datasets versionne déjà les items, et la vue "Dataset Runs" compare nativement plusieurs runs dans le temps. Le coût est quasi gratuit à obtenir : `trace_llm_call` passe déjà `model_id` à chaque generation, donc Langfuse calcule déjà le coût USD automatiquement — pas de tracking manuel à ajouter.

Déclenché en `workflow_dispatch` uniquement (pas sur chaque PR) : le dataset va grossir (DoD `notes.md`) et chaque run rappelle le vrai modèle Gemini — un coût réel à ne pas cacher derrière chaque push.

## Key Assumptions to Validate
- [ ] L'API exacte de sync/upsert d'items sur un Dataset via le SDK Python Langfuse v4 (créer vs mettre à jour un item existant par id) — à vérifier dans la doc Langfuse avant d'écrire le script, ne pas coder de mémoire (principe du skill `langfuse`).
- [ ] `document_id` comme clé unique d'item Langfuse dans le Dataset `gold-devis` — chaque `document_id` du YAML pointe désormais vers un `source_file` distinct (le doublon initial entre les documents 2 et 3, qui partageaient par erreur `26-0727 Super U Exincourt...pdf`, a été corrigé : le document 3 pointe maintenant vers `Devis n° 6952.pdf`, cohérent avec son annotation `numero_devis: "n°6952"`).
- [ ] La marge de tolérance numérique et le format de comparaison de date à utiliser dans le matching normalisé (le YAML actuel contient des valeurs hétérogènes, ex. `duree_validite_offre: "1 mois"` vs `"30/05/2026"` pour un champ typé `date` côté `FieldType`) — à trancher au moment d'écrire les évaluateurs, pas dans cette spec.

## MVP Scope

**In :**
- Retrait de `data_test/` du `.gitignore` (uniquement les PDF référencés par `tests/data/dataset_gold_devis.yaml`, pas tout le dossier) — committés en clair, quelques Mo.
- Script de sync YAML → Dataset Langfuse `gold-devis` (upsert par `document_id`).
- Script d'éval : `dataset.run_experiment(name=..., task=<pipeline réel>, evaluators=[...], run_evaluators=[...])`.
- Évaluateurs item-level : match normalisé par type de champ (texte insensible casse/espaces, tolérance numérique, comparaison date ISO), TP/FP/FN par champ (valeur erronée = 1 FP + 1 FN, convention standard slot-filling), exact-match document (tous les champs corrects), latence, coût (lu depuis `cost_details` de la trace).
- Évaluateurs run-level : Precision/Recall/F1 macro (moyenne inter-champs) et micro (agrégée), exact-match accuracy globale, coût total/moyen, latence p50/p95, **split OCR vs non-OCR** (réutilise la dimension `pages_ocr` déjà tracée par `trace_pdf_extraction`), grounding accuracy (page extraite vs `evidence.page` gold, sur les valeurs correctes uniquement — donnée déjà présente dans le gold, aucune instrumentation nouvelle).
- Documents `human_validation: false` **exclus des métriques principales**, reportés à part (compte + score indicatif).
- Workflow `.github/workflows/eval-gold-dataset.yml`, `workflow_dispatch`, avec input optionnel `LLM_MODEL` (comparer des modèles sans changer de code).
- Résumé texte dans `$GITHUB_STEP_SUMMARY` (tableau des métriques run-level + lien direct vers le run Langfuse) — pas de dépendance à `langfuse/experiment-action` pour l'instant (voir Not Doing).
- Secrets CI réutilisés du même jeu que Cloud Run : `GOOGLE_GENERATIVE_AI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.

## Not Doing (and Why)
- **Gate bloquant (seuils de régression / `RegressionError`)** — dataset encore petit (14 documents), pas assez d'historique de runs pour fixer des seuils fiables. Activable plus tard sans re-architecture : c'est un changement du script d'éval, pas du mécanisme de sync/run.
- **Déclenchement automatique sur PR/push** — coût Gemini caché à chaque commit, non souhaité tant que le dataset grossit. Le trigger `workflow_dispatch` peut être étendu à `schedule` ou `pull_request` plus tard sans changer le reste du pipeline.
- **Git LFS / bucket GCS pour les PDF** — quelques Mo committés en clair suffisent, cohérent avec l'esprit "interface simple / faible jeu de données" du `CLAUDE.md`. À revisiter si `data_test/` dépasse quelques dizaines de Mo.
- **Correction du gold depuis l'UI Langfuse** — le YAML git reste la seule source de vérité éditable ; le Dataset Langfuse n'est qu'un miroir synchronisé à chaque run, jamais édité à la main côté Langfuse. Une future UI de validation dans l'app elle-même (déjà notée dans `notes.md`) resterait l'endroit pour corriger le gold, pas Langfuse.
- **Indice de confiance sur l'extraction** (`notes.md`, section "Amélioration pipeline NER") — sujet de modélisation distinct, hors périmètre d'une CI d'évaluation.
- **`langfuse/experiment-action` (action GitHub officielle)** — pensée pour du gating avec commentaires de PR ; peu de valeur sans déclencheur PR et sans seuils. Un script custom + `$GITHUB_STEP_SUMMARY` est plus simple pour du reporting-only. Réévaluable si on bascule un jour vers un trigger PR + gate.
- **Artefact JSON des métriques run-level en dehors de Langfuse** (ex. attaché au run GitHub Actions) — l'UI Langfuse suffit comme unique point de consultation, pas besoin d'un second chemin d'accès hors-ligne.

## Open Questions
Aucune à ce stade — les points ouverts de la première passe (nom du dataset, doublon `document_id`, accès hors-ligne aux métriques) ont été tranchés ci-dessus.
