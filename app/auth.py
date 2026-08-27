import base64
import binascii
import os

from fasthtml.common import Beforeware, Response


def _valid_credentials(header: str | None, username: str, password: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    user, _, pwd = decoded.partition(":")
    return user == username and pwd == password


def basic_auth_beforeware() -> Beforeware | None:
    """Beforeware FastHTML exigeant un Basic Auth valide sur toute requête.

    Désactivé (None) si BASIC_AUTH_USER/BASIC_AUTH_PASSWORD ne sont pas
    définis — même convention que NoOpTracer/les clés d'extraction : absent
    en local = fonctionnalité désactivée, toujours défini sur Cloud Run via
    Secret Manager.
    """
    username = os.getenv("BASIC_AUTH_USER")
    password = os.getenv("BASIC_AUTH_PASSWORD")
    if not username or not password:
        return None

    def _check(req):
        if _valid_credentials(req.headers.get("authorization"), username, password):
            return None
        return Response(
            "Authentification requise",
            status_code=401,
            headers={"WWW-Authenticate": "Basic"},
        )

    return Beforeware(_check)
