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

**État actuel (2026-09-03, suite) : cible < 1 min toujours NON atteinte,
mais un 2e gain réel et vérifié via un changement d'architecture.** Cold
start baseline ~288s → ~186s (config prod, Leviers 1-6) → **~120-153s
(médiane ~153s) avec le moteur vLLM piloté en mono-process
(`scripts/modal_nuextract_server_singleprocess.py`, expérimental, pas
encore en prod)**, aucune régression gold (F1 identique, mêmes tp/fp/fn
qu'avec le serveur actuel). Root cause du reste identifiée précisément
(voir "Décomposition précise" plus bas) : la marge restante est dominée
par de l'overhead d'infrastructure (ordonnancement Modal + démarrage du 2e
process vLLM) plutôt que par quelque chose d'encore réglable via un flag
vLLM.

**Session du 2026-09-03 (suite 2, sur demande explicite -- tester
l'architecture mono-process malgré le coût d'implémentation)** : la piste
"sortir du CLI `vllm serve`" listée en fin de section précédente comme non
tentée a été testée. Root-causée via lecture du code source vLLM installé
(pas de supposition) : `AsyncLLM` (utilisé par `vllm serve`) ignore
totalement `VLLM_ENABLE_V1_MULTIPROCESSING` -- seule l'API offline
synchrone (`vllm.LLM`) le respecte. Un serveur expérimental construit
autour de `vllm.LLM.chat()` donne ~120-153s, un gain net d'environ 30s
supplémentaires par rapport à la config prod actuelle, confirmé par les
logs serveur (voir Levier 7 plus bas) -- toujours pas sous la barre des 60s
visée, et avec un compromis de concurrence à trancher avant adoption
éventuelle en prod.

Session du 2026-09-02 : investigation rigoureuse (root-cause vérifiée via
les logs serveur à chaque étape, pas de supposition) qui n'avait pas
encore abouti à un fix net, plus une conclusion intermédiaire erronée
(GPU snapshot) détectée et corrigée en cours de route.
Session du 2026-09-03 (suite, sur signalement utilisateur) : le vrai
goulot a été isolé (compilation JIT Triton, ~100s+ par cold start) et
corrigé en le déplaçant du runtime vers le build de l'image -- gain net
et vérifié. Incident en cours de route (déploiement cassé, corrigé en
quelques minutes) et deux pistes supplémentaires testées sans effet,
toutes documentées ci-dessous.

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

---

### Suite (2026-09-03) — le vrai goulot isolé et corrigé

**Levier 4 — pré-compiler les kernels Triton dans l'image (build-time),
pas dans un volume (runtime) — testé, GAGNANT, retenu.** Le Levier 3 avait
identifié le bon symptôme (JIT Triton) mais la mauvaise solution
(persistance via volume, jamais confirmée fiable). Nouvelle approche :
`Image.run_function(_warmup_image_kernels, gpu="L4", ...)` — démarre
`vllm serve` **une seule fois, au build de l'image**, envoie une requête à
taille d'image réaliste (page A4 150dpi synthétique via Pillow), arrête
proprement. Les kernels compilés atterrissent dans le cache Triton par
défaut (`~/.triton/cache`), capturé dans le layer de l'image — présent
dans **tout** conteneur créé à partir de cette image, sans dépendre d'un
volume externe.

**Incident en cours de route (outage complet, corrigé immédiatement)** :
le premier essai a cassé la production. vLLM écrit aussi dans
`/root/.cache/vllm` par défaut (pas seulement `~/.triton/cache`) ; ce
dossier non-vide baked dans l'image entrait en conflit avec le montage du
volume `vllm_cache` au même chemin au runtime → `cannot mount volume on
non-empty path` → **crash-loop total, 0% de requêtes réussies** pendant
~20 min avant détection (signalé par l'utilisateur : cold start toujours
> 3 min, en réalité pire — échecs purs). Fix : `shutil.rmtree("/root/.cache/vllm")`
en fin de fonction de build, avant que Modal ne capture le layer —
redéployé, vérifié en quelques minutes.

**Résultat mesuré (une fois le fix appliqué)** : `init engine (profile,
create kv cache, warmup model)` passé de ~121s à **~15-20s** (log réel).
Cold start total : **6 cycles sur 2 sessions de test, 154-218s** (médiane
~187s) — baisse nette et stable par rapport à la baseline ~288s, sans
régression gold (F1 identique : tp=47, fp=22, fn=19).

**Levier 5 — `HF_HUB_OFFLINE=1` — testé, sans effet.** Les logs montraient
un appel réseau au HF Hub au démarrage ("Warning: You are sending
unauthenticated requests to the HF Hub") alors que le modèle est déjà
entièrement en cache local. Désactivé par précaution — **aucun changement
mesuré** (3 cycles : 186-190s, identique à avant). Gardé quand même (pas
de coût, légitime en soi : aucune raison de faire des appels réseau
évitables).

**Diagnostic (gratuit, sans GPU) — temps d'import Python.** Avant de
creuser plus loin dans l'hypothèse "les imports sont lents", mesuré
directement via `scripts/_diag_import_time.py`
(`python -X importtime -c "import vllm"` dans l'image réelle, function
Modal CPU-only) : **`import vllm` complet ne prend que ~8.8s**. Écarte
l'hypothèse d'un import Python lourd comme goulot dominant — le temps
restant va ailleurs (voir décomposition ci-dessous).

**Levier 6 — `VLLM_ENABLE_V1_MULTIPROCESSING=0` — testé, INEFFICACE,
retiré.** Hypothèse : vLLM V1 démarre un 2e process (EngineCore) séparé de
l'APIServer, chacun initialisant CUDA indépendamment ; un seul process
éviterait cette double init. Le flag est bien pris en compte (log réel :
"Since VLLM_ENABLE_V1_MULTIPROCESSING is set to False, this may affect the
random state...") **mais EngineCore reste un process séparé** (pid
distinct de l'APIServer dans les logs, confirmé sur une trace complète) —
le split ne se désactive pas ainsi dans cette version de vLLM (0.28.0).
Aucun gain mesuré (3 cycles : 185-218s, un cycle non garanti froid
exclu), effet de bord ajouté (seed aléatoire) sans contrepartie : retiré.

**Décomposition précise du cold start restant** (trace complète d'un
cycle, logs non filtrés, `modal app logs --since/--until`, Levier 6 —
la structure est la même sans ce levier) :

| Étape | Durée | Notes |
|---|---|---|
| Tunnel Modal ouvert → banner process démarré | **~34s** | Ordonnancement/placement du conteneur par l'infra Modal — hors de notre contrôle via la config applicative. |
| Banner → "Initializing a V1 LLM engine" (EngineCore) | **~40s** | Fork + imports du 2e process (EngineCore). `import vllm` seul ne prend que 8.8s (mesuré) — le reste est probablement l'init CUDA/NCCL de ce process, pas l'import Python en tant que tel. |
| Engine annoncé → début du chargement du modèle | **~19s** | Setup du backend distribué (NCCL, même pour 1 seul GPU) + import transformers dans ce process. |
| Chargement des poids | **~13s** | Rapide, déjà optimisé (prefetch safetensors), pas de marge significative ici. |
| Poids chargés → KV cache/encoder cache prêts | **~15s** | Allocation mémoire, indépendant du profiling déjà sauté par `--kv-cache-memory`. |
| Warmup kernels Triton | **~5s** | **Corrigé par le Levier 4** — était ~100s+ avant. |
| Warmup multimodal (vLLM) | **~20-25s** | Calcul réel (pas juste de la compilation), semble nécessaire à chaque démarrage même avec les kernels déjà compilés. |
| **Total** | **~150-155s** | Cohérent avec les cycles mesurés (154-190s, l'écart restant est la granularité du polling retry côté client). |

**Lecture** : ~93s sur ~153s (61%) sont dans les deux premières lignes —
ordonnancement Modal + démarrage du 2e process vLLM — ni l'un ni l'autre
réglable par un flag `vllm serve` connu à ce stade. Un changement de type
de GPU (A10G) n'a **pas** été testé : ces deux postes sont CPU/infra-bound,
pas GPU-compute-bound, donc l'analyse ne prédit aucun gain attendu là — le
coût réel d'un test (rebuild complet + plusieurs cycles) n'a pas semblé
justifié face à cette hypothèse défavorable, mais reste une piste
possible si l'hypothèse s'avère fausse à l'usage.

### Suite (2026-09-03, session 2) — architecture mono-process

**Levier 7 — piloter `vllm.LLM` (API offline synchrone) directement en
Python plutôt que `vllm serve` (CLI, API async) — testé, GAGNANT sur le
cold start, mais avec un compromis de concurrence non trivial. Pas encore
adopté en prod.**

**Diagnostic préalable (gratuit, CPU-only, lecture du code source vLLM
0.28.0 réellement installé -- `scripts/_diag_engine_arch.py`,
`scripts/_diag_llm_offline_api.py`, `scripts/_diag_sampling_defaults.py`,
tous jetables)**, avant tout cycle payant sur GPU :

- `AsyncLLM.__init__` (utilisé par `vllm serve`, notre serveur actuel)
  appelle **inconditionnellement**
  `EngineCoreClient.make_async_mp_client(...)`, qui retourne toujours un
  client multiprocess. `VLLM_ENABLE_V1_MULTIPROCESSING` n'est **jamais lu**
  sur ce chemin de code -- ceci confirme et explique, avec le code source à
  l'appui, l'échec du Levier 6 (le flag était bien "pris en compte" quelque
  part dans les logs, mais sur un chemin de code -- `LLMEngine`, pas
  `AsyncLLM` -- qui n'est pas celui emprunté par `vllm serve`).
- `LLMEngine` (utilisé par l'API offline synchrone `vllm.LLM`) lit bien cet
  env var (`vllm/v1/engine/llm_engine.py:157`) et, si mis à `0`, obtient un
  `InprocClient` -- l'EngineCore tourne dans le **même process**, aucun
  fork. C'est le seul chemin mono-process disponible dans cette version de
  vLLM.
- `LLM.chat()` accepte `chat_template_kwargs` et des messages multimodaux
  exactement comme le serveur OpenAI (même mécanisme interne) -- pas besoin
  de réimplémenter l'application du chat template à la main.
- `SamplingParams.max_tokens` vaut `16` par défaut si non fourni -- le
  serveur OpenAI vLLM calcule sa propre valeur par défaut à partir du
  contexte restant (code non localisé précisément, plusieurs refactors
  entre versions) ; repris ici comme une constante fixe plus simple à
  raisonner (`_MAX_COMPLETION_TOKENS = 4096`, calculée à la main à partir
  de `_WINDOW_SIZE_PAGES`/`--max-model-len`, voir le commentaire dans le
  fichier) plutôt que répliquer ce calcul dynamique.

**Implémentation** : `scripts/modal_nuextract_server_singleprocess.py`.
Remplace `subprocess.Popen(_vllm_command())` par `vllm.LLM(...)` construit
une fois dans `@modal.enter()`, servi par un serveur HTTP minimal (stdlib
`http.server.ThreadingHTTPServer`, aucune dépendance ajoutée) qui traduit
`POST /v1/chat/completions` en un appel `llm.chat(...)` -- juste assez de
l'API OpenAI pour rester compatible avec `scripts/nuextract_client.py`
(SDK `openai`) sans le modifier. Même config moteur que
`scripts/modal_nuextract_server.py` (`_engine_kwargs()` -- équivalent
`EngineArgs` de chaque flag CLI de `_vllm_command()`), même stratégie de
warmup Triton au build (`Image.run_function`, mêmes précautions
`shutil.rmtree("/root/.cache/vllm")` que le Levier 4).

**Déployé sur une app Modal séparée**
(`nuextract3-singleprocess-experiment`, pas `nuextract3`) pour ne jamais
risquer la prod pendant l'expérimentation -- l'incident de crash-loop du
Levier 4 avait eu lieu directement sur l'app de prod.

**Compromis assumé, documenté, pas encore tranché** : `vllm.LLM.chat()`
est bloquant. Le serveur maison sérialise les requêtes via un verrou
global (`self.server.llm_lock`) -- une seule extraction à la fois, pas de
continuous batching multi-requêtes comme `AsyncLLM`/`vllm serve` le
permettent nativement. Sans effet sur la latence d'une requête isolée
(déjà `max_containers=1`), mais un usage concurrent réel (ex.
`nuextract_gold_langfuse_eval.py`, `max_concurrency=14`) serait sérialisé
au lieu d'être traité en parallèle sur le GPU -- à réévaluer avant toute
adoption en prod au-delà de l'expérimentation.

**Résultat mesuré** :

- Cold start, 3 cycles forcés : **120.1s, 152.7s, 152.6s (médiane
  ~152.7s)**, contre 184.5-189.6s (médiane ~185.8s) pour la config prod
  actuelle sur les mêmes 3 cycles de référence -- un gain net d'environ
  30s.
- Régression gold (18 documents) : **F1 0.6963 (tp=47, fp=22, fn=19,
  tn=32) -- identique bit pour bit à la config prod actuelle**, y compris
  le même document en échec pré-existant (`Offre BRIAND Métal...pdf`, bug
  windowing hors scope, message d'erreur légèrement différent --
  `VLLMValidationError` en 500 au lieu d'un `BadRequestError` en 400 --
  parce que le serveur maison ne réplique pas la validation de longueur de
  prompt du serveur OpenAI officiel avant de soumettre la requête au
  moteur ; même cause, pas une nouvelle régression).
- Décomposition d'un cycle via les logs serveur horodatés (`modal app logs
  --timestamps`, méthodologie inchangée -- pas de supposition) : du
  démarrage du process (`non-default args` loggé) à l'ouverture du tunnel
  Modal (serveur prêt), **86s au total**, contre ~112-117s pour les étapes
  équivalentes en config prod (hors ordonnancement Modal, externe aux deux
  architectures). Le gain se concentre précisément là où l'hypothèse le
  prédisait : "process start → engine annoncé" passe de ~40s (fork + import
  du 2e process) à ~23s (pas de fork, juste la résolution de config), et
  "engine annoncé → début chargement poids" passe de ~19s à ~2s (plus de
  second `distributed_init_method`/init NCCL à recréer pour un 2e
  process). Le chargement des poids (~11s), la préparation du KV cache
  (~16s) et le warmup multimodal (~25s, calcul réel, pas de la
  compilation) restent inchangés -- attendu, ces étapes ne dépendent pas
  de l'architecture process.

**Décision** : gain réel et vérifié, mais **pas encore adopté en
production** -- nécessite un arbitrage sur le compromis de concurrence
(sérialisation) avant de remplacer `scripts/modal_nuextract_server.py`.
Laissé comme fichier expérimental séparé et déployé sur une app Modal
distincte, documenté ici pour référence future.

## Table détaillée

| Date | Levier | Config (diff) | Cold start (s) — cycles individuels | Régression gold (F1, tp/fp/fn) | Décision | Notes |
|---|---|---|---|---|---|---|
| 2026-09-02 | Baseline (config déjà optimisée avant ce chantier) | `--enforce-eager`, cache vLLM persistant, `--safetensors-load-strategy prefetch`, `--max-num-seqs 8` (voir `scripts/modal_nuextract_server.py`) | 288.2, 320.5, 284.1 (médiane 288.2 ; retry-wait 245.0/275.0/245.0) | F1 0.696 (tp=47, fp=22, fn=19) — 17/18 documents scorés, 1 en échec (`Offre BRIAND Métal...pdf`, `Input length (17275) exceeds model's maximum context length (16384)` — bug windowing pré-existant, **hors scope de ce chantier**, non corrigé ici) | Référence | Chiffre à battre : < 60s en régime établi. Variabilité faible sur ces 3 cycles (284-320s, écart ~13%). Le bug windowing sur ce document sert de référence "connue" pour les leviers suivants. |
| 2026-09-02 | **GPU memory snapshot Modal (alpha) + vLLM `--enable-sleep-mode`** — 1er test (cycles rapprochés) | `enable_memory_snapshot=True` + `experimental_options={"enable_gpu_snapshot": True}` sur `@app.server` ; `VLLM_SERVER_DEV_MODE=1` ; `--enable-sleep-mode` ; `@modal.enter(snap=True)` démarre + warmup + `POST /sleep?level=1` ; `@modal.enter(snap=False)` = `POST /wake_up` | 9 cycles, dans l'ordre : 248.6, 283.7, 450.5, **52.1**, **31.1**, **29.2**, **55.6**, 346.3, **55.7** — cycles 1-3 (build du snapshot) lents comme attendu ; sur les 6 cycles "régime établi" (4-9) : 5/6 sous 60s (29-56s, médiane ~54s), 1/6 outlier à 346.3s | F1 0.711 (tp=48, fp=21, fn=18) vs baseline F1 0.696 — équivalent | **Gardé initialement** (décision revue plus bas — voir ligne "Correction") | Conclusion initiale : gain net dans le cas majoritaire. **Cette conclusion s'est révélée trompeuse** — voir ligne suivante. Le biais : ces 9 cycles s'enchaînent en quelques minutes via le harness (`modal container stop` puis requête immédiate), pas représentatif d'un usage réel espacé. |
| 2026-09-02 | **CORRECTION — GPU snapshot re-testé en usage réel (requêtes espacées de plusieurs minutes)** | Même config que ci-dessus, aucun changement de code — seule la façon de déclencher les cold starts change (usage réel / `nuextract_gold_langfuse_eval.py` de l'utilisateur, puis un test dédié à une seule requête après attente naturelle) | 3 tentatives réalistes : (1) 1er cold start après redeploy — reconstruction complète attendue, lente ; (2) **~13 min plus tard** — reconstruction complète à nouveau (`Starting to load model...` réapparaît, alors qu'un snapshot valide existait déjà) ; (3) **~12-16 min plus tard**, requête unique non concurrente — restauration réussie mais lente (`Restoring Function from memory snapshot.` à 16:18:11, `POST /wake_up` seulement à 16:20:57 -- ~2m46 d'écart) | Non re-mesuré (config retirée avant) | **RETIRÉ** — gain non fiable en usage réel, risque de pénalité nette | Root cause de chaque comportement confirmée via `modal app logs --since/--until` (pas supposée) : (1) attendu, 1er usage d'une nouvelle version déployée n'a pas encore de snapshot. (2) inattendu et non expliqué par la doc Modal disponible — un snapshot déjà construit n'a pas été réutilisé après ~13 min d'inactivité. (3) le snapshot **a** été trouvé et utilisé, mais l'opération de restauration elle-même a été lente (~2m46), confirmant que même une restauration "réussie" n'est pas fiable en délai. Sur 3 tentatives à intervalle réaliste : **0/3 restauration rapide**. Repris dans `scripts/modal_nuextract_server.py` : décorateur, `VLLM_SERVER_DEV_MODE`, `--enable-sleep-mode`, méthodes `_wait_ready`/`_post`/`_warmup`/`start_and_sleep`/`wake` tous retirés. |
| 2026-09-02 | **`--kv-cache-memory=10382653748`** (saute le profiling mémoire vLLM) | Ajouté à la commande `vllm serve`, sans le snapshot GPU (retiré ci-dessus) | 5 cycles : 319.6, 88.3*, 252.2, 250.6, 283.4 (*cycle non garanti froid — timeout de confirmation d'arrêt, `forced_cold=false`, exclu de l'analyse) | Non re-mesuré (aucun gain, pas de risque de régression fonctionnelle de toute façon — flag purement performance) | **Gardé** (aucun coût, mais aucun bénéfice mesuré non plus — voir notes) | Confirmé actif dans les logs : `reserved 9.67 GiB memory for KV Cache as specified by kv_cache_memory_bytes config and skipped memory profiling`. Mais `init engine (profile, create kv cache, warmup model)` reste à 95-124s sur tous les cycles malgré le profiling sauté — la mesure mémoire n'était qu'une sous-étape rapide de ce bloc de 121s, pas le goulot principal. Root cause affinée par le levier suivant. |
| 2026-09-02 | **`TRITON_CACHE_DIR=/root/.cache/vllm/triton`** (persiste le cache Triton dans le volume déjà monté) | `.env()` de l'image + réutilisation du volume `vllm_cache` existant (pas de nouveau volume) | 4 cycles : 353.1 (1er, compile attendu), 256.7, 317.7, 222.8 | Non re-mesuré | **Retiré** (remplacé par le Levier 4, voir ci-dessous) | Root cause affinée par lecture complète des logs (pas de filtre) : silence total de ~1m46-2m entre un warning `tl.make_block_ptr is deprecated` (compilation Triton en cours) et la reprise des logs, sur **chaque** cycle y compris le dernier. Le volume contient pourtant ~120 entrées de cache après ces cycles -- le cache est écrit mais ne semble pas relu efficacement d'un conteneur au suivant (probablement la fiabilité du commit de volume, jamais confirmée -- non-problème avec l'approche du Levier 4, qui n'a plus besoin de volume pour ce cache). |
| 2026-09-03 | **Kernels Triton baked dans l'image (build-time)** — 1er essai | `Image.run_function(_warmup_image_kernels, gpu="L4", volumes={hf_cache})` -- démarre vllm serve au build, warmup, arrête | 2 cycles : **échec total** (580.2s, 575.7s -- budget de retry client épuisé, `InternalServerError 503`) | Non mesurable (serveur down) | **Bug critique, corrigé en urgence** | `modal app logs` : `Runner failed with exception: cannot mount volume on non-empty path: "/root/.cache/vllm"` en boucle -- `Function ... is crash-looping`. vLLM écrit dans ce dossier par défaut au build ; le layer d'image obtenu entre en conflit avec le montage du volume `vllm_cache` au même chemin au runtime. **Outage de production le temps du diagnostic (~20 min).** |
| 2026-09-03 | **Kernels Triton baked dans l'image** — fix (`shutil.rmtree` avant fin de build) | Idem + nettoyage de `/root/.cache/vllm` en fin de `_warmup_image_kernels` | 3 cycles : 186.4, 154.3, 187.1 | Non re-mesuré à ce stade (voir "final-config" plus bas) | **Gardé** | `init engine (profile, create kv cache, warmup model)` : 121s → **15.54s** (log réel). Root cause du Levier 3 confirmée a posteriori : c'était bien le JIT Triton, la persistance par image plutôt que par volume a résolu le problème de fiabilité. |
| 2026-09-03 | **`HF_HUB_OFFLINE=1`** | `.env()` de l'image | 3 cycles : 186.0, 188.2, 190.0 | Non re-mesuré (flag sans risque fonctionnel) | **Gardé** (pas de coût) | Aucun changement mesuré -- l'appel réseau HF Hub n'était pas un goulot significatif, juste un avertissement dans les logs. |
| 2026-09-03 | **`VLLM_ENABLE_V1_MULTIPROCESSING=0`** | `.env()` de l'image | 3 cycles : 218.3, 31.2*, 185.7 (*cycle non garanti froid, `forced_cold=false`, exclu) | Non re-mesuré | **Retiré** | Flag pris en compte (log : affecte le seed aléatoire) mais **n'a pas fusionné les 2 process** -- `EngineCore pid` reste distinct de `APIServer pid` sur une trace complète. Hypothèse "double init CUDA" non éliminée par ce flag dans vLLM 0.28.0. Aucun gain, effet de bord ajouté : retiré. |
| 2026-09-03 | **Config finale** (Levier 4 + `--kv-cache-memory` + `HF_HUB_OFFLINE`, sans snapshot/`TRITON_CACHE_DIR` volume/multiprocessing) | Voir `scripts/modal_nuextract_server.py` (état final) | 3 cycles de vérification : 184.5, 185.8, 189.6 (médiane 185.8) | F1 0.6963 (tp=47, fp=22, fn=19) -- **identique à la baseline**, même document en échec pré-existant | **Config de production** | Gain vérifié et stable : baseline ~288s → ~186s, soit **~35% de réduction**, sans aucune régression fonctionnelle sur 2 vérifications gold indépendantes (Levier 4 initial + config finale). |
| 2026-09-03 (suite) | **Levier 7 — `vllm.LLM` mono-process au lieu de `vllm serve`** | `scripts/modal_nuextract_server_singleprocess.py`, app Modal séparée (`nuextract3-singleprocess-experiment`), `VLLM_ENABLE_V1_MULTIPROCESSING=0` + `vllm.LLM.chat()` derrière un serveur HTTP maison (stdlib), requêtes sérialisées (verrou global) | 3 cycles : 120.1, 152.7, 152.6 (médiane 152.7) | F1 0.6963 (tp=47, fp=22, fn=19, tn=32) -- **identique à la config prod**, même document en échec pré-existant (message d'erreur différent, même cause) | **Gain confirmé, pas encore adopté en prod** | ~30s de gain net vs config prod (185.8 → 152.7 médiane). Root-causé via logs horodatés : le gain vient bien de l'élimination du fork EngineCore (~40s → ~23s sur "process start → engine annoncé", ~19s → ~2s sur "engine annoncé → chargement poids"). Compromis non tranché : sérialisation des requêtes (pas de continuous batching) -- voir section dédiée pour le détail. |

## Pistes pour la suite (non résolues à ce stade)

- **Ordonnancement Modal (~34s)** : hors de notre contrôle via la config
  applicative actuelle — pourrait varier selon la région/le type de GPU,
  non testé (voir décomposition ci-dessus, hypothèse défavorable : coût
  CPU/infra-bound, pas GPU-compute-bound).
- **Démarrage du 2e process vLLM (EngineCore, ~40-59s)** — **testé et
  résolu (Levier 7)**, mais pas encore adopté en prod. Piloter `vllm.LLM`
  (API offline synchrone) au lieu de `vllm serve` élimine effectivement ce
  coût (~30s de gain net, confirmé par les logs) mais sérialise les
  requêtes (plus de continuous batching multi-requêtes) — arbitrage à
  trancher avant un remplacement de `scripts/modal_nuextract_server.py`
  (voir la section dédiée ci-dessus).
- **Warmup multimodal vLLM (~20-25s)** : semble être du calcul réel
  (profiling), pas juste de la compilation — pas de flag connu pour le
  sauter sans risquer une latence spike sur la première vraie requête.
  Inchangé par le Levier 7 (même coût dans les deux architectures).
- **GPU alternatif (A10G/A100)** : non testé, analyse défavorable (voir
  ci-dessus) mais pas définitivement exclu.
- **Quantization** : toujours écartée (aucun checkpoint officiel
  NuExtract3), deviendrait pertinente si le chargement des poids (~13s,
  déjà rapide) redevenait un goulot après d'autres optimisations.
