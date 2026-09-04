"""Diagnostic jetable, CPU-only. Voir docs/nuextract-cold-start-tests.md."""

import subprocess

import modal

app = modal.App("nuextract3-diag-sampling-defaults")

image = modal.Image.debian_slim(python_version="3.12").pip_install("vllm")


@app.function(image=image, timeout=180)
def inspect():
    import vllm

    root = vllm.__path__[0]

    print("=== to_sampling_params dans chat_completion/protocol.py ===")
    r = subprocess.run(
        ["grep", "-n", "-A50", "def to_sampling_params",
         f"{root}/entrypoints/openai/chat_completion/protocol.py"],
        capture_output=True, text=True,
    )
    print(r.stdout)

    print("\n=== max_tokens field def dans chat_completion/protocol.py ===")
    r2 = subprocess.run(
        ["grep", "-n", "-B2", "-A5", "max_tokens",
         f"{root}/entrypoints/openai/chat_completion/protocol.py"],
        capture_output=True, text=True,
    )
    print(r2.stdout)


@app.local_entrypoint()
def main():
    inspect.remote()
