import base64
import io

from PIL import Image as PILImage

from scripts.modal_nuextract_server import (
    MODEL_NAME,
    _WARMUP_IMAGE_SIZE_PX,
    _synthetic_page_png_base64,
    _vllm_command,
)


def test_vllm_command_contains_critical_cold_start_flags():
    """Filet offline (pas de GPU requis) sur `_vllm_command()` -- garde une
    trace testée des flags dont l'absence a coûté un cycle de déploiement
    réel pendant l'investigation cold start (voir
    docs/nuextract-cold-start-tests.md). Ne remplace pas une vérification
    réelle (le comportement de vLLM lui-même n'est pas testé ici), juste un
    filet contre une régression de configuration triviale."""
    cmd = _vllm_command()

    assert cmd[:3] == ["vllm", "serve", MODEL_NAME]
    assert "--enforce-eager" in cmd
    assert "--trust-remote-code" in cmd

    for flag, value in [
        ("--max-model-len", "16384"),
        ("--max-num-seqs", "8"),
        ("--kv-cache-memory", "10382653748"),
        ("--safetensors-load-strategy", "prefetch"),
    ]:
        assert flag in cmd, f"{flag} absent de la commande"
        assert cmd[cmd.index(flag) + 1] == value, f"valeur inattendue pour {flag}"


def test_synthetic_page_png_base64_matches_warmup_image_size():
    """L'image de warmup au build doit avoir la taille déclarée
    (`_WARMUP_IMAGE_SIZE_PX`) -- c'est cette taille qui doit correspondre à
    une page réelle pour que le warmup compile les bons kernels Triton
    (voir docstring de `_warmup_image_kernels`)."""
    image_b64 = _synthetic_page_png_base64()
    image = PILImage.open(io.BytesIO(base64.b64decode(image_b64)))

    assert image.format == "PNG"
    assert image.size == _WARMUP_IMAGE_SIZE_PX
