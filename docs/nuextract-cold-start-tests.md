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
| 2026-09-02 | **GPU memory snapshot Modal (alpha) + vLLM `--enable-sleep-mode`** | `enable_memory_snapshot=True` + `experimental_options={"enable_gpu_snapshot": True}` sur `@app.server` ; `VLLM_SERVER_DEV_MODE=1` ; `--enable-sleep-mode` ; `@modal.enter(snap=True)` démarre + warmup + `POST /sleep?level=1` ; `@modal.enter(snap=False)` = `POST /wake_up` (voir `scripts/modal_nuextract_server.py`) | 9 cycles, dans l'ordre : 248.6, 283.7, 450.5, **52.1**, **31.1**, **29.2**, **55.6**, 346.3, **55.7** — cycles 1-3 (build du snapshot) lents comme attendu ; sur les 6 cycles "régime établi" (4-9) : 5/6 sous 60s (29-56s, médiane ~54s), **1/6 outlier à 346.3s** | F1 0.711 (tp=48, fp=21, fn=18) vs baseline F1 0.696 — équivalent (même document en échec pré-existant, `Offre BRIAND Métal...pdf`, même cause) | **Gardé comme nouvelle config par défaut** — gain net dans le cas majoritaire, pas pire que la baseline dans le pire cas | **Root cause de l'outlier, identifiée via `modal app logs`** (pas une supposition) : le log serveur affiche `Restoring Function from memory snapshot.` quasi immédiatement, mais l'appel `POST /wake_up` (notre code, `@modal.enter(snap=False)`) ne se déclenche que ~2m30 plus tard sur ce cycle — une fois appelé, le wake-up lui-même prend toujours ~1.2-1.3s (log vLLM `abstract.py:356`). Le goulot est donc **côté infrastructure de restore Modal, pas côté vLLM/notre code** — cohérent avec l'avertissement officiel Modal ("le checkpoint/restore au niveau driver est encore récent"). Les leviers de Phase 2 (réglages vLLM, image, quantization) ciblent le chemin de démarrage *à froid*, pas le chemin de *restore* -- ils n'auraient probablement aucun effet sur cet outlier précis. Le pire cas mesuré (450.5s) reste **dans le budget de retry client déjà existant** (~515s, `scripts/nuextract_client.py`), donc pas de régression de robustesse même sur un cycle lent. |

| Date | Levier | Config (diff) | Cold start (s) — cycles individuels | Régression gold (F1, tp/fp/fn) | Décision | Notes |
|---|---|---|---|---|---|---|
| 2026-09-02 | Baseline (config actuelle) | `--enforce-eager`, cache vLLM persistant, `--safetensors-load-strategy prefetch`, `--max-num-seqs 8` (déjà en place, voir `scripts/modal_nuextract_server.py`) | 288.2, 320.5, 284.1 (médiane 288.2 ; retry-wait 245.0/275.0/245.0) | F1 0.696 (tp=47, fp=22, fn=19) — 17/18 documents scorés, 1 en échec (`Offre BRIAND Métal...pdf`, `Input length (17275) exceeds model's maximum context length (16384)` — bug windowing pré-existant, **hors scope de ce chantier**, non corrigé ici) | Référence | Chiffre à battre : < 60s en régime établi. Variabilité faible sur ces 3 cycles (284-320s, écart ~13%) — cohérent avec la borne basse déjà documentée (`scripts/nuextract_client.py`), pas avec le pire cas observé historiquement (jusqu'à ~515s). Le bug windowing sur ce document sert de référence "connue" pour les leviers suivants — s'il réapparaît identique, pas une nouvelle régression ; s'il change de nature, à investiguer. |

