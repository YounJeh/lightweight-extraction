"""Diagnostic jetable, CPU-only (pas de GPU) : inspecte l'API offline
`vllm.LLM` (moteur synchrone, mono-process quand
VLLM_ENABLE_V1_MULTIPROCESSING=0 -- confirmé par
scripts/_diag_engine_arch.py) pour savoir si `.chat()` accepte les mêmes
paramètres que le serveur OpenAI (`chat_template_kwargs`, contenu image,
EngineArgs équivalents à `_vllm_command()`), avant d'implémenter un serveur
HTTP maison par-dessus. Voir docs/nuextract-cold-start-tests.md.

Usage : uv run modal run scripts/_diag_llm_offline_api.py
"""

import inspect as pyinspect

import modal

app = modal.App("nuextract3-diag-llm-offline-api")

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "vllm",
    "huggingface_hub",
)


@app.function(image=image, timeout=300)
def inspect():
    from vllm import LLM
    from vllm.engine.arg_utils import EngineArgs

    print("=== LLM.__init__ signature ===")
    print(pyinspect.signature(LLM.__init__))

    print("\n=== LLM.chat signature ===")
    print(pyinspect.signature(LLM.chat))

    print("\n=== LLM.chat docstring ===")
    print(pyinspect.getdoc(LLM.chat))

    print("\n=== EngineArgs fields relevant (max_num_seqs, kv_cache_memory,"
          " safetensors_load_strategy, enforce_eager, limit_mm_per_prompt,"
          " trust_remote_code) ===")
    sig = pyinspect.signature(EngineArgs.__init__)
    for name in [
        "max_num_seqs",
        "kv_cache_memory_bytes",
        "kv_cache_memory",
        "safetensors_load_strategy",
        "enforce_eager",
        "limit_mm_per_prompt",
        "trust_remote_code",
        "max_model_len",
        "generation_config",
        "chat_template_content_format",
    ]:
        present = name in sig.parameters
        print(f"{name}: {'PRESENT' if present else 'absent'}")

    print("\n=== LLM.generate signature (fallback si .chat trop haut niveau) ===")
    print(pyinspect.signature(LLM.generate))


@app.local_entrypoint()
def main():
    inspect.remote()
