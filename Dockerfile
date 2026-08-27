# Dockerfile de repli pour Cloud Run — voir specs/deploy-cloud-run.md.
# Nécessaire (pas juste un fallback de détection) : rapidocr dépend en dur
# de opencv-python (variante GUI, a besoin de libGL/libxcb absents d'un
# environnement serveur) alors qu'on veut opencv-python-headless. Le
# buildpack source-based ne garantit pas que opencv-python-headless "gagne"
# l'installation sur le même chemin cv2/ (confirmé cassé en prod avec
# ImportError: libxcb.so.1 — voir choix_techniques.md), donc ce Dockerfile
# corrige ça explicitement après uv sync plutôt que de parier sur un ordre
# d'installation.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Étape séparée pour profiter du cache Docker : un changement de code seul
# (sans toucher pyproject.toml/uv.lock) ne réinstalle pas toute la stack
# OCR/CV (~150 Mo, la partie la plus lente de ce sync).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .
RUN uv sync --frozen --no-dev

# Désinstaller puis réinstaller à neuf, pas juste désinstaller
# opencv-python : les deux paquets installent des fichiers au même chemin
# (cv2/), donc le RECORD de opencv-python peut lister des fichiers que
# opencv-python-headless a effectivement écrits en dernier — le désinstaller
# seul risquerait de supprimer les fichiers headless réellement utilisés.
RUN uv pip uninstall opencv-python opencv-python-headless \
    && uv pip install opencv-python-headless

ENV PORT=8080
EXPOSE 8080

# --no-sync : sans ça, "uv run" resynchronise l'environnement sur uv.lock à
# chaque démarrage du conteneur (uv.lock déclare toujours opencv-python, via
# rapidocr) — ça réinstallerait la variante GUI et annulerait le fix
# ci-dessus à chaque nouvelle instance/redémarrage.
CMD ["uv", "run", "--no-sync", "python", "-m", "app.main"]
