"""Diagnostic jetable (pas un script de prod), CPU-only (pas de GPU, donc
gratuit) : inspecte le code source vLLM réellement installé pour savoir
si un mode mono-process existe pour l'EngineCore (V1), avant de tenter un
changement d'architecture coûteux (sortir du CLI `vllm serve`). Le levier
`VLLM_ENABLE_V1_MULTIPROCESSING=0` a déjà été testé et n'a pas fusionné les
process (voir docs/nuextract-cold-start-tests.md, Levier 6) -- on regarde
ici directement le code pour comprendre pourquoi, et si `LLM` (moteur
offline synchrone) a un chemin différent de `AsyncLLM`/`vllm serve`.

Usage : uv run modal run scripts/_diag_engine_arch.py
"""

import subprocess

import modal

app = modal.App("nuextract3-diag-engine-arch")

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "vllm",
    "huggingface_hub",
)


@app.function(image=image, timeout=300)
def inspect():
    import importlib
    import inspect as pyinspect

    import vllm

    print("=== vllm.__version__ ===")
    print(vllm.__version__)

    print("\n=== grep VLLM_ENABLE_V1_MULTIPROCESSING dans le package vllm ===")
    grep = subprocess.run(
        ["grep", "-rn", "VLLM_ENABLE_V1_MULTIPROCESSING", vllm.__path__[0]],
        capture_output=True,
        text=True,
    )
    print(grep.stdout)

    print("\n=== grep multiprocess_mode / InprocClient / MPClient (core_client) ===")
    grep2 = subprocess.run(
        ["grep", "-rln", "InprocClient", vllm.__path__[0]],
        capture_output=True,
        text=True,
    )
    print(grep2.stdout)

    for modname in [
        "vllm.v1.engine.core_client",
        "vllm.v1.engine.async_llm",
    ]:
        try:
            mod = importlib.import_module(modname)
        except Exception as exc:
            print(f"\n=== import {modname} FAILED: {exc} ===")
            continue
        print(f"\n=== source: {modname} (fichier: {mod.__file__}) ===")

    print("\n=== EngineCoreClient.make_client / make_async_mp_client signature ===")
    try:
        from vllm.v1.engine.core_client import EngineCoreClient

        for name in ("make_client", "make_async_mp_client"):
            fn = getattr(EngineCoreClient, name, None)
            if fn is not None:
                print(f"--- {name} ---")
                print(pyinspect.getsource(fn))
    except Exception as exc:
        print(f"FAILED: {exc}")

    print("\n=== AsyncLLM.from_engine_args / from_vllm_config source ===")
    try:
        from vllm.v1.engine.async_llm import AsyncLLM

        for name in ("from_engine_args", "from_vllm_config", "__init__"):
            fn = getattr(AsyncLLM, name, None)
            if fn is not None:
                print(f"--- {name} ---")
                print(pyinspect.getsource(fn))
    except Exception as exc:
        print(f"FAILED: {exc}")

    print("\n=== api_server.py: comment le serveur OpenAI construit l'engine ===")
    grep3 = subprocess.run(
        ["grep", "-rn", "multiprocess_mode\\|AsyncLLM.from_\\|build_async_engine_client",
         f"{vllm.__path__[0]}/entrypoints/openai/api_server.py"],
        capture_output=True,
        text=True,
    )
    print(grep3.stdout)

    print("\n=== vllm serve --help (extrait multiprocessing/frontend) ===")
    help_out = subprocess.run(["vllm", "serve", "--help"], capture_output=True, text=True)
    for line in help_out.stdout.splitlines():
        if "multiproc" in line.lower() or "frontend" in line.lower() or "engine" in line.lower():
            print(line)


@app.local_entrypoint()
def main():
    inspect.remote()
