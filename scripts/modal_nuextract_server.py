"""Déploiement du serveur NuExtract (vLLM + numind/NuExtract3) sur Modal —
GPU à la demande (L4, scale-to-zero), API compatible OpenAI consommée par
scripts/nuextract_client.py. Voir specs/nuextract-pipeline-spike.md.

Déploiement :
    modal deploy scripts/modal_nuextract_server.py

L'URL renvoyée (`https://<workspace>--nuextract3-nuextractserver-serve.modal.run`,
suffixée `/v1`) va dans NUEXTRACT_BASE_URL (.env) ; NUEXTRACT_API_KEY peut
rester vide (`unauthenticated=True` ci-dessous, "EMPTY" en repli côté client).
"""

import subprocess
import modal

MODEL_NAME = "numind/NuExtract3"
PORT = 8000

app = modal.App("nuextract3")

hf_cache = modal.Volume.from_name(
    "nuextract-hf-cache",
    create_if_missing=True,
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "vllm",
        "huggingface_hub",
    )
)


@app.server(
    image=image,
    gpu="L4",
    port=PORT,

    # 0 = aucun GPU allumé quand tu ne l'utilises pas
    min_containers=0,

    # garde le serveur 5 min après un appel
    scaledown_window=300,

    # chargement du modèle
    startup_timeout=600,

    # évite de multiplier les GPU pendant tes premiers tests
    max_containers=1,

    volumes={
        "/root/.cache/huggingface": hf_cache,
    },

    # pratique pour tester l'API directement
    unauthenticated=True,
)
class NuExtractServer:

    @modal.enter()
    def start_server(self):
        cmd = [
            "vllm",
            "serve",
            MODEL_NAME,

            "--host",
            "0.0.0.0",

            "--port",
            str(PORT),

            "--trust-remote-code",

            "--chat-template-content-format",
            "openai",

            "--generation-config",
            "vllm",

            # Important sur une L4 24 Go :
            # commence petit
            "--max-model-len",
            "16384",

            "--limit-mm-per-prompt",
            '{"image": 6, "video": 0}',
        ]

        subprocess.Popen(cmd)
