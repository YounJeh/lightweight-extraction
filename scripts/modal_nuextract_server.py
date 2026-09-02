"""Déploiement du serveur NuExtract (vLLM + numind/NuExtract3) sur Modal.

Objectifs :
- GPU L4 à la demande avec scale-to-zero.
- Cache Hugging Face persistant.
- Cache vLLM persistant.
- Cold start réduit avec --enforce-eager.
- Préchargement des poids safetensors.
- Concurrence limitée à 8 séquences.

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

    # Garde le container chaud pendant 60 s après la dernière requête.
    # À augmenter plus tard si les appels arrivent par batch/rafales.
    scaledown_window=60,

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
