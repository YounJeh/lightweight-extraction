"""Déploiement du serveur NuExtract (vLLM + numind/NuExtract3) sur Modal.

Objectifs :
- GPU L4 à la demande avec scale-to-zero.
- Cache Hugging Face persistant.
- Cache vLLM persistant.
- Cold start réduit avec --enforce-eager.
- Préchargement des poids safetensors.
- Concurrence limitée à 8 séquences.
- Cold start réduit en sautant le profiling mémoire vLLM via
  --kv-cache-memory (voir tasks/plan-nuextract-cold-start-optimization.md,
  Task 4bis, et docs/nuextract-cold-start-tests.md pour le contexte complet
  -- y compris l'essai GPU memory snapshot Modal + sleep mode, testé puis
  abandonné : peu fiable en usage réel espacé, root-causé via les logs
  serveur plutôt que supposé).

Déploiement :
    modal deploy scripts/modal_nuextract_server.py

L'URL renvoyée :
    https://<workspace>--nuextract3-nuextractserver-serve.modal.run

L'API OpenAI-compatible est disponible sous :
    /v1/chat/completions
"""

import subprocess

import modal


MODEL_NAME = "numind/NuExtract3"
PORT = 8000


app = modal.App("nuextract3")


# ---------------------------------------------------------------------------
# Caches persistants
# ---------------------------------------------------------------------------

# Poids/tokenizer/config Hugging Face.
hf_cache = modal.Volume.from_name(
    "nuextract-hf-cache",
    create_if_missing=True,
)

# Cache vLLM :
# torch.compile, kernels compilés et autres artefacts vLLM.
#
# Avec --enforce-eager il sera moins sollicité qu'en mode compilé,
# mais on le conserve pour éviter de reperdre les artefacts si on
# réactive torch.compile plus tard ou si vLLM y stocke d'autres caches.
vllm_cache = modal.Volume.from_name(
    "nuextract-vllm-cache",
    create_if_missing=True,
)


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "vllm",
        "huggingface_hub",
    )
    # FlashInfer sampler essaie sinon de compiler un kernel JIT nécessitant
    # nvcc, qui n'est pas présent dans cette image.
    #
    # On garde donc le sampler PyTorch natif.
    .env(
        {
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            # Les kernels Triton écrits à la main (attention MM, GDN linear
            # attn, etc.) sont JIT-compilés par Triton directement -- pas
            # via torch.compile (désactivé par --enforce-eager), donc pas
            # couverts par le cache torch.compile de vLLM
            # (~/.cache/vllm/torch_compile_cache, déjà dans le volume
            # vllm_cache monté ci-dessous). Triton a son propre cache
            # (TRITON_CACHE_DIR, ~/.triton/cache par défaut -- jamais
            # persisté jusqu'ici). Repointé dans vllm_cache pour survivre
            # aux cold starts : log réel observé, ~1m46 de silence complet
            # entre un warning Triton et la reprise des logs, sans ce fix.
            "TRITON_CACHE_DIR": "/root/.cache/vllm/triton",
        }
    )
)


# ---------------------------------------------------------------------------
# Serveur
# ---------------------------------------------------------------------------

@app.server(
    image=image,
    gpu="L4",
    port=PORT,

    # Aucun GPU lorsque le service n'est pas utilisé.
    min_containers=0,

    # Garde le container chaud 120s après la dernière requête -- juste de
    # quoi absorber des appels rapprochés (import par lot) sans repayer un
    # cold start à chaque fois.
    scaledown_window=120,

    # NuExtract + vLLM peuvent rester assez longs à initialiser.
    startup_timeout=600,

    # Un seul GPU pour l'instant.
    max_containers=1,

    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },

    # Tests uniquement.
    unauthenticated=True,
)
class NuExtractServer:

    @modal.enter()
    def start_server(self):
        cmd = [
            "vllm",
            "serve",
            MODEL_NAME,

            # ----------------------------------------------------------------
            # HTTP server
            # ----------------------------------------------------------------

            "--host",
            "0.0.0.0",

            "--port",
            str(PORT),

            # ----------------------------------------------------------------
            # Model
            # ----------------------------------------------------------------

            "--trust-remote-code",

            "--chat-template-content-format",
            "openai",

            "--generation-config",
            "vllm",

            # ----------------------------------------------------------------
            # Context
            # ----------------------------------------------------------------

            "--max-model-len",
            "16384",

            # ----------------------------------------------------------------
            # Cold start
            # ----------------------------------------------------------------
            #
            # Désactive torch.compile / CUDA graphs et exécute le modèle
            # directement en eager mode.
            #
            # Objectif : sacrifier éventuellement un peu de throughput
            # pour réduire fortement le cold start sur Modal scale-to-zero.
            #
            "--enforce-eager",

            # vLLM exécute normalement un forward pass de profiling pour
            # déterminer combien de mémoire allouer au KV cache -- mesuré à
            # 121s sur ce modèle/GPU (log réel : "init engine (profile,
            # create kv cache, warmup model) took 121.00 s"). Fournir la
            # valeur directement saute cette mesure.
            #
            # Valeur reprise telle quelle du message que vLLM lui-même a
            # loggé lors d'un run sans ce flag ("Replace gpu_memory_utilization
            # config with --kv-cache-memory=10382653748 (9.67 GiB) to fit
            # into requested memory") -- cohérente avec --max-model-len=16384
            # et --max-num-seqs=8 ci-dessous. À RECALCULER (relancer une fois
            # sans ce flag, relire la valeur suggérée dans les logs) si l'un
            # des deux change.
            "--kv-cache-memory",
            "10382653748",

            # ----------------------------------------------------------------
            # Concurrency
            # ----------------------------------------------------------------
            #
            # On n'a pas besoin de préparer des centaines de séquences
            # simultanées pour notre workload d'extraction documentaire.
            #
            "--max-num-seqs",
            "8",

            # ----------------------------------------------------------------
            # Weight loading
            # ----------------------------------------------------------------
            #
            # Le Volume Modal est vu comme un filesystem 9P.
            # Lors du run précédent, vLLM indiquait que l'auto-prefetch
            # était désactivé.
            #
            # On force donc le chargement des checkpoints dans le page cache
            # avant leur consommation par les workers.
            #
            "--safetensors-load-strategy",
            "prefetch",

            # ----------------------------------------------------------------
            # Multimodal
            # ----------------------------------------------------------------

            "--limit-mm-per-prompt",
            '{"image": 15, "video": 0}',
        ]

        subprocess.Popen(cmd)
