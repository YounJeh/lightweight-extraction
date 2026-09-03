"""Diagnostic jetable (pas un script de prod) : mesure le temps
d'import de vllm/torch/transformers dans l'image réelle du serveur
NuExtract, sans GPU -- juste pour savoir où va le temps avant de tester
une hypothèse coûteuse (cycle réel avec GPU). Voir
docs/nuextract-cold-start-tests.md.

Usage : uv run modal run scripts/_diag_import_time.py
"""

import subprocess

import modal

app = modal.App("nuextract3-diag-import-time")

image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "vllm",
    "huggingface_hub",
)


@app.function(image=image, timeout=300)
def measure():
    out = subprocess.run(
        ["python", "-X", "importtime", "-c", "import vllm"],
        capture_output=True,
        text=True,
    )
    lines = out.stderr.splitlines()
    # Trie par temps cumulé (colonne 2), garde le top 30.
    parsed = []
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) < 3:
            continue
        try:
            cumulative_us = int(parts[1].strip())
        except ValueError:
            continue
        parsed.append((cumulative_us, parts[2].strip()))
    parsed.sort(reverse=True)
    for cumulative_us, name in parsed[:30]:
        print(f"{cumulative_us/1000:8.1f} ms  {name}")


@app.local_entrypoint()
def main():
    measure.remote()
