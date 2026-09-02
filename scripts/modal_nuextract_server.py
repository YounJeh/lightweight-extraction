"""Déploiement du serveur NuExtract (vLLM + numind/NuExtract3) sur Modal.

Objectifs :
- GPU L4 à la demande avec scale-to-zero.
- Cache Hugging Face persistant.
- Cache vLLM persistant.
- Cold start réduit avec --enforce-eager.
- Préchargement des poids safetensors.
- Concurrence limitée à 8 séquences.
- Cold start encore réduit via GPU memory snapshot Modal (alpha) + sleep
  mode vLLM (voir tasks/plan-nuextract-cold-start-optimization.md, Task 4) :
  au premier démarrage (avant snapshot), le serveur charge le modèle,
  s'auto-teste (warmup), puis se met en veille (POST /sleep?level=1,
  poids déchargés vers la RAM CPU) -- c'est cet état "chaud mais endormi"
  que Modal snapshotte. Un cold start suivant restaure ce snapshot puis
  réveille juste le serveur (POST /wake_up), au lieu de rejouer tout le
  chargement depuis le Volume.

Déploiement :
    modal deploy scripts/modal_nuextract_server.py

L'URL renvoyée :
    https://<workspace>--nuextract3-nuextractserver-serve.modal.run

L'API OpenAI-compatible est disponible sous :
    /v1/chat/completions
"""

import http.client
import json
import subprocess
import time

import modal


MODEL_NAME = "numind/NuExtract3"
PORT = 8000

# PNG 1x1 transparent -- payload minimal pour exercer le chemin de code
# multimodal complet pendant le warmup, sans dépendre de pymupdf (non
# installé dans cette image) ni d'un vrai document.
_WARMUP_IMAGE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
            # Expose /sleep, /wake_up, /is_sleeping sur le serveur API vLLM
            # -- endpoints "dev", non exposés par défaut (voir
            # https://docs.vllm.ai/en/latest/features/sleep_mode/). Appelés
            # uniquement en localhost depuis ce même fichier (@modal.enter),
            # jamais via l'URL publique Modal -- pas un risque d'exposition.
            "VLLM_SERVER_DEV_MODE": "1",
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

    # Garde le container chaud pendant 600 s après la dernière requête.
    # À augmenter plus tard si les appels arrivent par batch/rafales.
    scaledown_window=600,

    # NuExtract + vLLM peuvent rester assez longs à initialiser.
    startup_timeout=600,

    # Un seul GPU pour l'instant.
    max_containers=1,

    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },

    # GPU memory snapshot (alpha, opt-in) -- voir
    # tasks/plan-nuextract-cold-start-optimization.md, Task 4. Support GPU
    # L4 non confirmé explicitement par la doc Modal (exemples officiels :
    # a10/a10g/h100) -- à valider par la mesure réelle, pas supposé.
    enable_memory_snapshot=True,
    experimental_options={"enable_gpu_snapshot": True},

    # Tests uniquement.
    unauthenticated=True,
)
class NuExtractServer:

    def _vllm_command(self) -> list[str]:
        return [
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

            # ----------------------------------------------------------------
            # Sleep mode (snapshot cold start, voir docstring module)
            # ----------------------------------------------------------------
            "--enable-sleep-mode",
        ]

    def _wait_ready(self, timeout: float = 570.0) -> None:
        """Poll /health jusqu'à ce que vLLM réponde -- `timeout` sous
        `startup_timeout=600` (marge pour warmup + mise en veille avant que
        Modal ne considère le démarrage en échec)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
                try:
                    conn.request("GET", "/health")
                    if conn.getresponse().status == 200:
                        return
                finally:
                    conn.close()
            except OSError:
                pass
            time.sleep(1)
        raise TimeoutError("vLLM n'est pas devenu ready avant le timeout")

    def _post(self, path: str, *, timeout: float = 120.0) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
        try:
            conn.request("POST", path)
            conn.getresponse().read()
        finally:
            conn.close()

    def _warmup(self, attempts: int = 2) -> None:
        """Envoie quelques requêtes réelles avant la mise en veille --
        exerce le chemin de code multimodal complet (comme l'exemple
        officiel Modal vLLM+snapshot) pour que le snapshot capture un état
        déjà sollicité, pas juste un modèle chargé mais jamais utilisé.
        Image 1x1 minimale (_WARMUP_IMAGE_PNG_BASE64) : le contenu n'a pas
        d'importance, seul le chemin de code compte."""
        body = json.dumps(
            {
                "model": MODEL_NAME,
                "temperature": 0,
                "max_tokens": 16,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": (
                                        "data:image/png;base64,"
                                        f"{_WARMUP_IMAGE_PNG_BASE64}"
                                    )
                                },
                            }
                        ],
                    }
                ],
                "chat_template_kwargs": {
                    "template": json.dumps({"warmup": "verbatim-string"})
                },
            }
        ).encode()

        for _ in range(attempts):
            conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=120)
            try:
                conn.request(
                    "POST",
                    "/v1/chat/completions",
                    body=body,
                    headers={"Content-Type": "application/json"},
                )
                conn.getresponse().read()
            finally:
                conn.close()

    @modal.enter(snap=True)
    def start_and_sleep(self):
        """Démarre vLLM, l'exerce (warmup), puis le met en veille (poids
        déchargés vers la RAM CPU, `level=1` -- récupération rapide, voir
        docstring module) juste avant que Modal ne prenne le snapshot GPU.
        Ne s'exécute qu'au (re)build du snapshot, pas à chaque cold start
        -- voir `wake` (`snap=False`) pour le chemin rapide."""
        self.process = subprocess.Popen(self._vllm_command())
        self._wait_ready()
        self._warmup()
        self._post("/sleep?level=1")

    @modal.enter(snap=False)
    def wake(self):
        """Restaure depuis le snapshot GPU (poids déjà en RAM CPU) --
        chemin rapide emprunté à chaque cold start une fois le snapshot
        construit."""
        self._post("/wake_up")
