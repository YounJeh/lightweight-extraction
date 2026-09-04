"""Expérimentation cold start NuExtract -- architecture mono-process.

Contexte : docs/nuextract-cold-start-tests.md ("Décomposition précise du
cold start restant") a isolé ~40-59s du cold start dans le démarrage d'un
2e process interne vLLM (EngineCore), inévitable avec `vllm serve`/`AsyncLLM`
-- confirmé par lecture du code source vLLM 0.28.0 installé
(`scripts/_diag_engine_arch.py`) : `AsyncLLM.__init__` appelle
inconditionnellement `EngineCoreClient.make_async_mp_client(...)`, qui
retourne toujours un client multiprocess -- `VLLM_ENABLE_V1_MULTIPROCESSING`
n'a **aucun effet** sur ce chemin (déjà testé, Levier 6 du fichier de
tests). Seule l'API offline synchrone (`vllm.LLM`, `LLMEngine`) respecte cet
env var et peut tourner en un seul process (`InprocClient`), confirmé via
le même diagnostic.

Ce fichier remplace donc `vllm serve` par `vllm.LLM.chat()` piloté
directement en Python, derrière un serveur HTTP minimal (stdlib
`http.server`, aucune dépendance supplémentaire) qui reproduit juste assez
de l'API OpenAI `/v1/chat/completions` pour rester compatible avec
`scripts/nuextract_client.py` (SDK `openai`) sans le modifier.

**Compromis assumé (documenté, pas caché)** : `vllm.LLM.chat()` est
bloquant -- une requête à la fois (verrou global), pas de batching continu
entre requêtes concurrentes comme `AsyncLLM`/`vllm serve` le permettent
nativement. Sur `max_containers=1` cela ne change rien à la latence d'une
requête isolée, mais un usage concurrent (ex. `nuextract_gold_langfuse_eval.py`,
`max_concurrency=14`) serait sérialisé au lieu d'être traité en continuous
batching -- acceptable pour un test de l'hypothèse cold start, à réévaluer
si cette architecture était retenue au-delà de l'expérimentation.

**App Modal séparée** (`nuextract3-singleprocess-experiment`, pas
`nuextract3`) -- ne touche jamais le déploiement de production
(`scripts/modal_nuextract_server.py`), pour ne pas répéter l'incident de
crash-loop du Levier 4 (voir docs/nuextract-cold-start-tests.md).

Déploiement :
    modal deploy scripts/modal_nuextract_server_singleprocess.py

Comparaison de cold start avec le harness existant :
    NUEXTRACT_BASE_URL=<url de ce déploiement> \\
        uv run python scripts/nuextract_cold_start_bench.py cold-start \\
        --label singleprocess --app-name nuextract3-singleprocess-experiment
"""

import http.server
import json
import shutil
import subprocess
import threading
import time

import modal


MODEL_NAME = "numind/NuExtract3"
PORT = 8000

# Identique à scripts/modal_nuextract_server.py -- page A4 à 150 dpi (voir
# `_RENDER_DPI` dans scripts/nuextract_client.py).
_WARMUP_IMAGE_SIZE_PX = (1240, 1754)

# Cf. `_WINDOW_SIZE_PAGES=4` (~11000 tokens estimés) et `--max-model-len
# 16384` -- budget restant pour la réponse ~5000 tokens. 4096 laisse une
# marge confortable pour un JSON de valeurs verbatim courtes, sans
# s'approcher de la limite. Le serveur OpenAI vLLM calcule normalement ceci
# dynamiquement (contexte restant réel) quand le client n'envoie pas
# `max_tokens` (notre cas, voir scripts/nuextract_client.py) -- ici on fixe
# une constante plus simple à raisonner pour cette expérimentation. À
# RECALCULER si `_WINDOW_SIZE_PAGES` ou `--max-model-len` changent.
_MAX_COMPLETION_TOKENS = 4096


def _engine_kwargs() -> dict:
    """Équivalent `EngineArgs` des flags CLI de `_vllm_command()` dans
    scripts/modal_nuextract_server.py -- doit rester en phase avec ce
    fichier pour que la comparaison de cold start ne mesure que le
    changement d'architecture serveur, pas une config moteur différente.
    Vérifié présent sur `EngineArgs`/`LLM.__init__` via
    scripts/_diag_llm_offline_api.py avant d'écrire ce fichier."""
    return dict(
        model=MODEL_NAME,
        trust_remote_code=True,
        generation_config="vllm",
        max_model_len=16384,
        enforce_eager=True,
        kv_cache_memory_bytes=10382653748,
        max_num_seqs=8,
        safetensors_load_strategy="prefetch",
        limit_mm_per_prompt={"image": 15, "video": 0},
    )


def _build_llm():
    from vllm import LLM

    return LLM(**_engine_kwargs())


def _synthetic_page_png_base64() -> str:
    """Identique à scripts/modal_nuextract_server.py -- dupliqué plutôt
    qu'importé pour garder ce fichier expérimental autonome (pas de
    dépendance croisée vers le module de production, plus simple à
    supprimer si l'expérimentation n'est pas retenue)."""
    import base64
    import io

    from PIL import Image as PILImage

    buffer = io.BytesIO()
    PILImage.new("RGB", _WARMUP_IMAGE_SIZE_PX, color="white").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _chat(llm, *, messages: list[dict], temperature: float, max_tokens: int, chat_template_kwargs):
    from vllm import SamplingParams

    sampling_params = SamplingParams(temperature=temperature, max_tokens=max_tokens)
    outputs = llm.chat(
        messages=messages,
        sampling_params=sampling_params,
        chat_template_kwargs=chat_template_kwargs,
        chat_template_content_format="openai",
        use_tqdm=False,
    )
    return outputs[0].outputs[0].text


def _warmup_image_kernels():
    """Exécuté une seule fois au build de l'image -- même rôle que
    `_warmup_image_kernels` dans scripts/modal_nuextract_server.py (compile
    les kernels Triton à la résolution d'image réelle), mais via
    `LLM.chat()` en Python directement plutôt qu'une requête HTTP à un
    process `vllm serve` lancé en subprocess."""
    llm = _build_llm()
    image_b64 = _synthetic_page_png_base64()
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                }
            ],
        }
    ]
    template_json = json.dumps({"warmup": "verbatim-string"})
    for _ in range(2):
        _chat(
            llm,
            messages=messages,
            temperature=0,
            max_tokens=16,
            chat_template_kwargs={"template": template_json},
        )
    del llm

    # Même précaution que la version production : vLLM écrit son propre
    # cache dans /root/.cache/vllm par défaut, qui entrerait en conflit
    # avec le montage du volume au même chemin au runtime si on le laisse
    # non-vide dans l'image (voir l'incident documenté dans
    # docs/nuextract-cold-start-tests.md).
    shutil.rmtree("/root/.cache/vllm", ignore_errors=True)


app = modal.App("nuextract3-singleprocess-experiment")


hf_cache = modal.Volume.from_name("nuextract-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("nuextract-vllm-cache", create_if_missing=True)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "vllm",
        "huggingface_hub",
        "pillow",
    )
    .env(
        {
            "VLLM_USE_FLASHINFER_SAMPLER": "0",
            "HF_HUB_OFFLINE": "1",
            # Critique pour cette expérimentation : force
            # `EngineCoreClient.make_client(multiprocess_mode=False, ...)`
            # -> `InprocClient` pour l'API offline synchrone (`LLM`).
            # Confirmé par lecture du code source vLLM installé
            # (scripts/_diag_engine_arch.py) -- vllm/v1/engine/llm_engine.py
            # lit cette variable, contrairement à `AsyncLLM` qui l'ignore
            # totalement (d'où l'échec du Levier 6 sur le serveur `vllm
            # serve`/production).
            "VLLM_ENABLE_V1_MULTIPROCESSING": "0",
        }
    )
    .run_function(
        _warmup_image_kernels,
        gpu="L4",
        volumes={"/root/.cache/huggingface": hf_cache},
        timeout=600,
    )
)


class _RequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 -- signature imposée par la stdlib
        pass  # Le logging par défaut de BaseHTTPRequestHandler écrit sur stderr à chaque requête -- bruit inutile ici.

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            max_tokens = (
                body.get("max_completion_tokens")
                or body.get("max_tokens")
                or _MAX_COMPLETION_TOKENS
            )
            with self.server.llm_lock:
                text = _chat(
                    self.server.llm,
                    messages=body["messages"],
                    temperature=body.get("temperature", 0.0),
                    max_tokens=max_tokens,
                    chat_template_kwargs=body.get("chat_template_kwargs"),
                )
        except Exception as exc:  # noqa: BLE001 -- renvoyé au client comme 500, jamais laissé planter le serveur
            payload = json.dumps({"error": {"message": repr(exc)}}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        response = {
            "id": "chatcmpl-singleprocess",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", MODEL_NAME),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            # Champ requis par le schéma de réponse du SDK openai, valeurs
            # non calculées ici (pas utilisées par scripts/nuextract_client.py).
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        payload = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler_cls, llm):
        super().__init__(address, handler_cls)
        self.llm = llm
        # Un seul appel à `llm.chat()` à la fois -- voir le compromis
        # documenté en tête de fichier (pas de continuous batching
        # multi-requêtes avec l'API offline synchrone).
        self.llm_lock = threading.Lock()


@app.server(
    image=image,
    gpu="L4",
    port=PORT,
    min_containers=0,
    scaledown_window=120,
    startup_timeout=600,
    max_containers=1,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },
    unauthenticated=True,
)
class NuExtractServerSingleProcess:

    @modal.enter()
    def start_server(self):
        llm = _build_llm()
        server = _Server(("0.0.0.0", PORT), _RequestHandler, llm)
        threading.Thread(target=server.serve_forever, daemon=True).start()
