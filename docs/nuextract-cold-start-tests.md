# Test log — cold start NuExtract/Modal

Cadrage : [docs/ideas/nuextract-cold-start-optimization.md](ideas/nuextract-cold-start-optimization.md).
Plan : [tasks/plan-nuextract-cold-start-optimization.md](../tasks/plan-nuextract-cold-start-optimization.md).

Log brut de chaque tentative (gain ou échec) — sert de trace complète pour
un entretien. Chaque mesure est produite par
`scripts/nuextract_cold_start_bench.py`, exécuté directement par l'agent
(autorisation explicite scopée à ce chantier, voir le plan). Données brutes
en JSONL dans `scripts/_cold_start_bench_cache/results.jsonl`.

**Méthodologie** : chaque cold start est forcé (arrêt explicite du
conteneur Modal actif, pas une simple attente du `scaledown_window`), puis
mesuré comme le temps entre l'envoi de la requête et la première réponse
réussie (retries internes du client inclus — c'est le temps réellement
subi par un appelant). Plusieurs cycles par config, jamais un seul run : un
snapshot Modal ne montre son plein effet qu'après quelques cold starts.
La non-régression est vérifiée sur les 18 documents du corpus gold
(`tests/data/dataset_gold_devis.yaml`), scorée comme
`gold_dataset_eval.py`/`gold_matching.py` (TP/FP/FN/FP, P/R/F1) mais sans
passer par Langfuse (boucle plus rapide pour itérer).

## Résumé

*(à compléter une fois le chantier conclu — voir Task 7 du todo)*

## Table détaillée

| Date | Levier | Config (diff) | Cold start (s) — cycles individuels | Régression gold (F1, tp/fp/fn) | Décision | Notes |
|---|---|---|---|---|---|---|
| 2026-09-02 | Baseline (config actuelle) | `--enforce-eager`, cache vLLM persistant, `--safetensors-load-strategy prefetch`, `--max-num-seqs 8` (déjà en place, voir `scripts/modal_nuextract_server.py`) | cycle 0 : 288.2 (dont 245.0 de retry-wait) — *(cycles 1-2 en cours)* | F1 0.696 (tp=47, fp=22, fn=19) — 17/18 documents scorés, 1 en échec (`Offre BRIAND Métal...pdf`, `Input length (17275) exceeds model's maximum context length (16384)` — bug windowing pré-existant, **hors scope de ce chantier**, non corrigé ici) | Référence | Chiffre à battre : < 60s en régime établi. Le bug windowing sur ce document sert de référence "connu" pour les leviers suivants — s'il réapparaît identique, pas une nouvelle régression ; s'il change de nature, à investiguer. |

