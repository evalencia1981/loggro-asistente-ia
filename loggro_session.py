"""
loggro_session.py
Cliente Loggro compartido por todo el backend (un solo login por proceso).

Antes cada módulo creaba su propio `LoggroClient`, lo que significaba un `POST /login`
extra por módulo (y el login de PirPos da 500 intermitente). Aquí vive el singleton.
"""
from __future__ import annotations

from typing import Optional

from loggro_client import LoggroClient

_cli: Optional[LoggroClient] = None


def cliente() -> LoggroClient:
    """Devuelve el cliente autenticado (hace login la primera vez)."""
    global _cli
    if _cli is None:
        c = LoggroClient()
        c.login()
        _cli = c
    return _cli


def reset() -> None:
    """Fuerza un login nuevo en la próxima llamada (token inválido, cambio de cuenta)."""
    global _cli
    _cli = None
