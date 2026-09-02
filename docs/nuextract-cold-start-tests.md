# Test log — cold start NuExtract/Modal

Cadrage : [docs/ideas/nuextract-cold-start-optimization.md](ideas/nuextract-cold-start-optimization.md).
Plan : [tasks/plan-nuextract-cold-start-optimization.md](../tasks/plan-nuextract-cold-start-optimization.md).

Log brut de chaque tentative (gain ou échec) — sert de trace complète pour
un entretien, y compris une conclusion revue en cours de route (voir
Résumé). Chaque mesure est produite par
`scripts/nuextract_cold_start_bench.py`, exécuté directement par l'agent
(autorisation explicite scopée à ce chantier, voir le plan). Données brutes
en JSONL dans `scripts/_cold_start_bench_cache/results.jsonl`.

**Méthodologie** : chaque cold start est forcé (arrêt explicite du
conteneur Modal actif via `modal container stop`, pas une simple attente
du `scaledown_window`), puis mesuré comme le temps entre l'envoi de la
requête et la première réponse réussie (retries internes du client
inclus — c'est le temps réellement subi par un appelant). Plusieurs
cycles par config, jamais un seul run. La non-régression est vérifiée sur
les 18 documents du corpus gold (`tests/data/dataset_gold_devis.yaml`),
scorée comme `gold_dataset_eval.py`/`gold_matching.py` (TP/FP/FN/TN,
P/R/F1) mais sans passer par Langfuse (boucle plus rapide pour itérer).

**Biais de méthode découvert en cours de route** (voir Levier 1
ci-dessous) : forcer des cycles rapprochés (`modal container stop` suivi
immédiatement d'une nouvelle requête) ne reproduit pas fidèlement un usage
réel espacé de plusieurs minutes — un levier peut sembler gagnant en test
rapproché et ne rien apporter en usage réel. Les leviers suivants ont donc
aussi été vérifiés avec au moins un cycle après un intervalle plus proche
d'un usage réel (plusieurs minutes, déclenché par une requête réelle
plutôt que par le harness).

## Résumé

**État actuel (2026-09-02, fin de session) : cible < 1 min NON atteinte.**
Cold start toujours dans une fourchette de ~220-350s après 3 leviers
testés en réel. Documenté ici pour ce que c'est : une investigation
rigoureuse (root-cause vérifiée via les logs serveur à chaque étape, pas
de supposition) qui n'a pas encore abouti à un fix, plus une conclusion
intermédiaire erronée détectée et corrigée en cours de route.

**Baseline** (config déjà optimisée avant ce chantier : eager mode, cache
vLLM, prefetch safetensors, `max-num-seqs=8`) : cold start ~284-320s
(médiane ~288s).

**Levier 1 — GPU memory snapshot Modal (alpha) + vLLM `--enable-sleep-mode`
— testé, puis RETIRÉ après re-test en usage réel.** Premier test (9 cycles
rapprochés via le harness) : 5/6 cycles en régime établi sous 60s,
concluant à tort à un gain net (voir la ligne "Correction" dans la table).
Un usage réel plus tard dans la session (requêtes espacées de plusieurs
minutes, comme le ferait `nuextract_gold_langfuse_eval.py`) a montré que
le snapshot n'était en réalité quasiment jamais réutilisé correctement :
sur 3 tentatives réalistes supplémentaires, 1 reconstruction complète
inattendue et 1 restauration lente, aucune restauration rapide — soit un
**gain nul, voire une pénalité nette** (la mise en veille + création du
snapshot ajoute ~2 min quand la reconstruction est nécessaire, ce qui
s'est avéré être le cas courant, pas l'exception). Retiré de la config.

**Levier 2 — `--kv-cache-memory` (saute le profiling mémoire vLLM) —
testé, sans effet.** Les logs serveur montraient
`init engine (profile, create kv cache, warmup model) took 121.00 s` sur
chaque cold start ; vLLM lui-même suggère une valeur à passer à
`--kv-cache-memory` pour sauter cette mesure. Implémenté, confirmé actif
dans les logs (`... skipped memory profiling`), **mais le temps total n'a
pas bougé** (5 cycles : 250-320s, essentiellement la baseline) — la
mesure mémoire n'était pas le vrai goulot, seulement une sous-étape du
bloc de 121s.

**Levier 3 — `TRITON_CACHE_DIR` persisté dans le volume vLLM — testé,
sans effet mesuré.** Root cause plus précise trouvée dans les logs : un
silence total de ~1m46 entre un warning de compilation Triton et la
reprise des logs, à chaque cold start — cohérent avec une recompilation
JIT des kernels Triton (attention, GDN linear attn) à chaque démarrage,
faute de cache persisté (Triton utilise son propre cache, distinct de
celui de `torch.compile` déjà couvert par le volume `vllm_cache`).
Implémenté (`TRITON_CACHE_DIR=/root/.cache/vllm/triton`), le volume
contient bien des dizaines d'entrées de cache après plusieurs cycles —
**mais le silence de ~2 min persiste sur le dernier cycle mesuré**, et le
temps total n'a pas baissé (4 cycles : 223-353s). Le cache est écrit mais
ne semble pas effectivement relu/réutilisé d'un conteneur au suivant.

**Piste ouverte, non vérifiée** : le harness force l'arrêt des conteneurs
via `modal container stop` (SIGINT), qui n'attend pas forcément la fin
d'un commit de volume en arrière-plan avant de tuer le processus — les
écritures dans `vllm_cache` (poids Triton compilés) pourraient ne jamais
être commitées avant que le conteneur suivant ne les cherche, ce qui
expliquerait un cache qui grossit sans jamais être effectivement relu.
Non confirmé — nécessiterait de comparer un arrêt "naturel" (laisser
`scaledown_window` s'écouler) à un arrêt forcé, ou d'inspecter les
horodatages de commit du volume directement.

**Levier écarté sans être testé** : quantization (AWQ/GPTQ/FP8) — NuExtract3
n'a aucun checkpoint quantifié officiel publié par numind (vérifié sur
[github.com/numindai/nuextract](https://github.com/numindai/nuextract)).

## Table détaillée

| Date | Levier | Config (diff) | Cold start (s) — cycles individuels | Régression gold (F1, tp/fp/fn) | Décision | Notes |
|---|---|---|---|---|---|---|
| 2026-09-02 | Baseline (config déjà optimisée avant ce chantier) | `--enforce-eager`, cache vLLM persistant, `--safetensors-load-strategy prefetch`, `--max-num-seqs 8` (voir `scripts/modal_nuextract_server.py`) | 288.2, 320.5, 284.1 (médiane 288.2 ; retry-wait 245.0/275.0/245.0) | F1 0.696 (tp=47, fp=22, fn=19) — 17/18 documents scorés, 1 en échec (`Offre BRIAND Métal...pdf`, `Input length (17275) exceeds model's maximum context length (16384)` — bug windowing pré-existant, **hors scope de ce chantier**, non corrigé ici) | Référence | Chiffre à battre : < 60s en régime établi. Variabilité faible sur ces 3 cycles (284-320s, écart ~13%). Le bug windowing sur ce document sert de référence "connue" pour les leviers suivants. |
| 2026-09-02 | **GPU memory snapshot Modal (alpha) + vLLM `--enable-sleep-mode`** — 1er test (cycles rapprochés) | `enable_memory_snapshot=True` + `experimental_options={"enable_gpu_snapshot": True}` sur `@app.server` ; `VLLM_SERVER_DEV_MODE=1` ; `--enable-sleep-mode` ; `@modal.enter(snap=True)` démarre + warmup + `POST /sleep?level=1` ; `@modal.enter(snap=False)` = `POST /wake_up` | 9 cycles, dans l'ordre : 248.6, 283.7, 450.5, **52.1**, **31.1**, **29.2**, **55.6**, 346.3, **55.7** — cycles 1-3 (build du snapshot) lents comme attendu ; sur les 6 cycles "régime établi" (4-9) : 5/6 sous 60s (29-56s, médiane ~54s), 1/6 outlier à 346.3s | F1 0.711 (tp=48, fp=21, fn=18) vs baseline F1 0.696 — équivalent | **Gardé initialement** (décision revue plus bas — voir ligne "Correction") | Conclusion initiale : gain net dans le cas majoritaire. **Cette conclusion s'est révélée trompeuse** — voir ligne suivante. Le biais : ces 9 cycles s'enchaînent en quelques minutes via le harness (`modal container stop` puis requête immédiate), pas représentatif d'un usage réel espacé. |
| 2026-09-02 | **CORRECTION — GPU snapshot re-testé en usage réel (requêtes espacées de plusieurs minutes)** | Même config que ci-dessus, aucun changement de code — seule la façon de déclencher les cold starts change (usage réel / `nuextract_gold_langfuse_eval.py` de l'utilisateur, puis un test dédié à une seule requête après attente naturelle) | 3 tentatives réalistes : (1) 1er cold start après redeploy — reconstruction complète attendue, lente ; (2) **~13 min plus tard** — reconstruction complète à nouveau (`Starting to load model...` réapparaît, alors qu'un snapshot valide existait déjà) ; (3) **~12-16 min plus tard**, requête unique non concurrente — restauration réussie mais lente (`Restoring Function from memory snapshot.` à 16:18:11, `POST /wake_up` seulement à 16:20:57 -- ~2m46 d'écart) | Non re-mesuré (config retirée avant) | **RETIRÉ** — gain non fiable en usage réel, risque de pénalité nette | Root cause de chaque comportement confirmée via `modal app logs --since/--until` (pas supposée) : (1) attendu, 1er usage d'une nouvelle version déployée n'a pas encore de snapshot. (2) inattendu et non expliqué par la doc Modal disponible — un snapshot déjà construit n'a pas été réutilisé après ~13 min d'inactivité. (3) le snapshot **a** été trouvé et utilisé, mais l'opération de restauration elle-même a été lente (~2m46), confirmant que même une restauration "réussie" n'est pas fiable en délai. Sur 3 tentatives à intervalle réaliste : **0/3 restauration rapide**. Repris dans `scripts/modal_nuextract_server.py` : décorateur, `VLLM_SERVER_DEV_MODE`, `--enable-sleep-mode`, méthodes `_wait_ready`/`_post`/`_warmup`/`start_and_sleep`/`wake` tous retirés. |
| 2026-09-02 | **`--kv-cache-memory=10382653748`** (saute le profiling mémoire vLLM) | Ajouté à la commande `vllm serve`, sans le snapshot GPU (retiré ci-dessus) | 5 cycles : 319.6, 88.3*, 252.2, 250.6, 283.4 (*cycle non garanti froid — timeout de confirmation d'arrêt, `forced_cold=false`, exclu de l'analyse) | Non re-mesuré (aucun gain, pas de risque de régression fonctionnelle de toute façon — flag purement performance) | **Gardé** (aucun coût, mais aucun bénéfice mesuré non plus — voir notes) | Confirmé actif dans les logs : `reserved 9.67 GiB memory for KV Cache as specified by kv_cache_memory_bytes config and skipped memory profiling`. Mais `init engine (profile, create kv cache, warmup model)` reste à 95-124s sur tous les cycles malgré le profiling sauté — la mesure mémoire n'était qu'une sous-étape rapide de ce bloc de 121s, pas le goulot principal. Root cause affinée par le levier suivant. |
| 2026-09-02 | **`TRITON_CACHE_DIR=/root/.cache/vllm/triton`** (persiste le cache Triton dans le volume déjà monté) | `.env()` de l'image + réutilisation du volume `vllm_cache` existant (pas de nouveau volume) | 4 cycles : 353.1 (1er, compile attendu), 256.7, 317.7, 222.8 | Non re-mesuré | **Gardé** (pas de coût, gain espéré non confirmé) | Root cause affinée par lecture complète des logs (pas de filtre) : silence total de ~1m46-2m entre un warning `tl.make_block_ptr is deprecated` (compilation Triton en cours) et la reprise des logs, sur **chaque** cycle y compris le dernier. Le volume contient pourtant ~120 entrées de cache après ces cycles (`modal volume ls nuextract-vllm-cache /triton`) -- le cache est écrit mais ne semble pas relu efficacement d'un conteneur au suivant. Hypothèse non confirmée : le harness arrête les conteneurs via SIGINT (`modal container stop`), qui pourrait couper le process avant qu'un commit de volume en arrière-plan ne soit terminé. |

## Pistes pour la suite (non lancées faute de temps/budget GPU dans cette session)

- Vérifier l'hypothèse de commit de volume : comparer un arrêt naturel
  (laisser `scaledown_window` s'écouler, pas de `container stop`) à un
  arrêt forcé, sur le cache Triton.
- Si confirmé : soit changer la méthode d'arrêt du harness pour du testing
  futur, soit accepter que ça n'aide pas en usage réel (le
  `scaledown_window` réel de prod n'utilise de toute façon jamais
  `container stop`, donc si le problème est spécifique au SIGINT du
  harness, la persistance pourrait déjà fonctionner correctement en usage
  réel — à vérifier avec un test réel non forcé).
- Phase 2 du plan (réglages vLLM restants, image plus fine, GPU
  alternatif) reste à explorer si les pistes ci-dessus n'aboutissent pas.
