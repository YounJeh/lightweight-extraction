"""Déploiement du serveur NuExtract (vLLM + numind/NuExtract3) sur Modal.

Objectifs :
- GPU L4 à la demande avec scale-to-zero.
- Cache Hugging Face persistant.
- Cache vLLM persistant.
- Cold start réduit avec --enforce-eager.
- Préchargement des poids safetensors.
- Concurrence limitée à 8 séquences.
- Cold start réduit en sautant le profiling mémoire vLLM via
  --kv-cache-memory.
- Cold start réduit en pré-compilant les kernels Triton **dans l'image
  elle-même** (`_warmup_image_kernels`, exécuté une seule fois au build,
  pas à chaque cold start) -- root-causé via les logs serveur (~1m46-2min
  de silence à chaque démarrage, JIT Triton) puis persisté d'abord via un
  volume (essai infructueux -- fiabilité du commit du volume jamais
  confirmée), maintenant baked-in à l'image. Voir
  docs/nuextract-cold-start-tests.md pour l'historique complet des essais,
  y compris le GPU memory snapshot Modal testé puis abandonné (peu fiable
  en usage réel espacé).

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

# Dimensions d'une page A4 rendue à 150 dpi (voir `_RENDER_DPI` dans
# scripts/nuextract_client.py) -- utilisées pour l'image de warmup au
# build, afin de compiler les kernels Triton de l'encodeur multimodal aux
# dimensions réellement utilisées en usage réel, pas juste le batch de
# profiling interne (taille arbitraire) de vLLM.
_WARMUP_IMAGE_SIZE_PX = (1240, 1754)


def _vllm_command() -> list[str]:
    """Commande `vllm serve` -- factorisée pour être strictement identique
    entre le démarrage réel (`NuExtractServer.start_server`) et le warmup
    exécuté au build de l'image (`_warmup_image_kernels`). Les deux
    doivent tourner avec exactement la même config pour que les kernels
    Triton compilés au build restent valides au runtime (les clés de
    cache Triton dépendent de la config)."""
    return [
        "vllm",
        "serve",
        MODEL_NAME,

        # --------------------------------------------------------------
        # HTTP server
        # --------------------------------------------------------------

        "--host",
        "0.0.0.0",

        "--port",
        str(PORT),

        # --------------------------------------------------------------
        # Model
        # --------------------------------------------------------------

        "--trust-remote-code",

        "--chat-template-content-format",
        "openai",

        "--generation-config",
        "vllm",

        # --------------------------------------------------------------
        # Context
        # --------------------------------------------------------------

        "--max-model-len",
        "16384",

        # --------------------------------------------------------------
        # Cold start
        # --------------------------------------------------------------
        #
        # Désactive torch.compile / CUDA graphs et exécute le modèle
        # directement en eager mode.
        #
        # Objectif : sacrifier éventuellement un peu de throughput
        # pour réduire fortement le cold start sur Modal scale-to-zero.
        #
        "--enforce-eager",

        # vLLM exécute normalement un forward pass de profiling pour
        # déterminer combien de mémoire allouer au KV cache. Fournir la
        # valeur directement saute cette mesure -- testé isolément, sans
        # effet mesurable sur le temps total (voir
        # docs/nuextract-cold-start-tests.md), mais gardé : aucun coût,
        # et la mesure mémoire elle-même n'a pas à être refaite à chaque
        # cold start.
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

        # --------------------------------------------------------------
        # Concurrency
        # --------------------------------------------------------------
        #
        # On n'a pas besoin de préparer des centaines de séquences
        # simultanées pour notre workload d'extraction documentaire.
        #
        "--max-num-seqs",
        "8",

        # --------------------------------------------------------------
        # Weight loading
        # --------------------------------------------------------------
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

        # --------------------------------------------------------------
        # Multimodal
        # --------------------------------------------------------------

        "--limit-mm-per-prompt",
        '{"image": 15, "video": 0}',
    ]


def _synthetic_page_png_base64() -> str:
    """PNG factice à la taille d'une vraie page rendue (voir
    `_WARMUP_IMAGE_SIZE_PX`) -- le contenu n'a aucune importance, seule la
    résolution compte pour déclencher la même spécialisation de kernel
    Triton qu'un vrai document. Pillow n'est utile qu'au build de l'image,
    jamais chargé au runtime réel du serveur."""
    import base64
    import io

    from PIL import Image as PILImage

    buffer = io.BytesIO()
    PILImage.new("RGB", _WARMUP_IMAGE_SIZE_PX, color="white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _warmup_image_kernels():
    """Exécuté **une seule fois, au build de l'image** (`Image.run_function`
    ci-dessous) -- pas à chaque cold start. Démarre vLLM (déclenche la
    compilation JIT des kernels Triton, root-causée comme le vrai goulot
    du cold start, voir docs/nuextract-cold-start-tests.md), envoie une
    requête à taille d'image réaliste, puis arrête proprement. Les
    fichiers écrits dans le cache Triton par défaut (`~/.triton/cache`,
    aucune variable d'environnement custom) pendant cette exécution sont
    capturés dans le layer de l'image -- disponibles immédiatement à
    chaque futur cold start, sans dépendre d'un volume externe (essai
    précédent via un volume monté : jamais confirmé fiable)."""
    import http.client
    import json
    import shutil
    import time

    process = subprocess.Popen(_vllm_command())
    try:
        deadline = time.monotonic() + 570
        ready = False
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
                try:
                    conn.request("GET", "/health")
                    if conn.getresponse().status == 200:
                        ready = True
                        break
                finally:
                    conn.close()
            except OSError:
                pass
            time.sleep(1)
        if not ready:
            raise TimeoutError("vLLM n'est pas devenu ready pendant le build de l'image")

        image_b64 = _synthetic_page_png_base64()
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
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                            }
                        ],
                    }
                ],
                "chat_template_kwargs": {
                    "template": json.dumps({"warmup": "verbatim-string"})
                },
            }
        ).encode()
        for _ in range(2):
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
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()

        # vLLM écrit son propre cache dans /root/.cache/vllm par défaut
        # (pas seulement le cache Triton, qui lui vit dans
        # ~/.triton/cache -- pas touché ici). Si on laisse ce dossier
        # non-vide dans l'image, le montage du volume vllm_cache au même
        # chemin échoue au runtime ("cannot mount volume on non-empty
        # path") -- crash-loop total, observé en réel sur ce déploiement.
        # Dans ce `finally` (pas juste en fin de fonction) pour nettoyer
        # même si le warmup échoue avant d'arriver ici -- même si un
        # build en échec ne capture normalement aucun layer, mieux vaut
        # ne pas dépendre de cette garantie implicitement.
        shutil.rmtree("/root/.cache/vllm", ignore_errors=True)


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
#
# Le cache Triton (le vrai goulot identifié, voir
# docs/nuextract-cold-start-tests.md) N'EST PLUS ici -- il est baked-in à
# l'image (_warmup_image_kernels ci-dessus), un essai via ce volume
# n'ayant montré aucun gain fiable.
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
        # Uniquement pour générer l'image de warmup au build
        # (_synthetic_page_png_base64) -- jamais utilisé au runtime réel.
        "pillow",
    )
    # FlashInfer sampler essaie sinon de compiler un kernel JIT nécessitant
    # nvcc, qui n'est pas présent dans cette image.
    #
    # On garde donc le sampler PyTorch natif.
    .env(
        {
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            # Log réel observé au démarrage : "Warning: You are sending
            # unauthenticated requests to the HF Hub" -- un appel réseau
            # au Hub a lieu au démarrage (résolution de repo/config) alors
            # que le modèle est déjà entièrement en cache local
            # (hf_cache). Mode offline : aucun appel réseau, lecture
            # directe du cache local -- testé pour voir si ça réduit l'un
            # des silences observés dans les logs au démarrage.
            "HF_HUB_OFFLINE": "1",
        }
    )
    # VLLM_ENABLE_V1_MULTIPROCESSING=0 essayé puis retiré : l'hypothèse
    # était de fusionner APIServer et EngineCore en un seul process (une
    # seule init CUDA au lieu de deux). Le flag est bien pris en compte
    # (log réel : "Since VLLM_ENABLE_V1_MULTIPROCESSING is set to False,
    # this may affect the random state...") mais EngineCore reste un
    # process séparé (pid distinct de l'APIServer dans les logs) -- le
    # split ne se désactive pas ainsi dans cette version de vLLM. Aucun
    # gain mesuré, un effet de bord (seed aléatoire) en plus : retiré. Voir
    # docs/nuextract-cold-start-tests.md pour le détail (trace complète
    # d'un cycle, ~40s attribués au démarrage de ce 2e process).
    # Pré-compile les kernels Triton (le vrai goulot du cold start, voir
    # docs/nuextract-cold-start-tests.md) une seule fois ici, au build --
    # capturés dans le layer de l'image, présents dans tout conteneur créé
    # à partir de cette image, sans dépendre d'un volume externe monté au
    # runtime. `hf_cache` monté pour réutiliser les poids déjà en cache
    # (évite un re-téléchargement HF au build).
    .run_function(
        _warmup_image_kernels,
        gpu="L4",
        volumes={"/root/.cache/huggingface": hf_cache},
        timeout=600,
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
        subprocess.Popen(_vllm_command())
