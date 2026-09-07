"""
acceso.py — Puerta de acceso a la API.

Por qué existe: hasta ahora cualquiera con la URL podía leer la cartera
(nombres, cédulas y celulares de los clientes — datos de terceros, no del
negocio) y, peor, crear gastos y movimientos reales en Loggro. No había ninguna
validación antes de los handlers.

Modelo: un código compartido, sin usuarios ni contraseñas por persona. Cuando el
código es correcto se entrega una cookie firmada; la cookie es lo que viaja en
cada petición, no el código.

Modos previstos:
  * "dueno" -> datos reales, lectura y escritura.
  * "demo"  -> datos ficticios y solo lectura.

CUIDADO con el modo demo: mientras no exista el módulo de datos ficticios, un
visitante en modo demo leería los datos REALES (sin poder escribir, pero
leyéndolos). Por eso ACCESO_CODIGO_DEMO NO debe definirse en producción hasta
que la fase 2 esté desplegada. Sin esa variable el modo demo no se puede abrir
y el botón ni siquiera aparece.

FALLA CERRADO: si no hay ACCESO_CODIGO en el entorno no se abre nada. Un gate de
seguridad que se desactiva solo cuando falta configuración no es un gate.
"""
from __future__ import annotations

import os
import hmac
import json
import time
import base64
import hashlib

COOKIE = "loggro_acceso"
DURACION = 30 * 24 * 3600  # 30 días

MODO_DUENO = "dueno"
MODO_DEMO = "demo"

# Un código corto se adivina a fuerza bruta. No es una contraseña de usuario:
# es un secreto compartido, así que puede (y debe) ser largo.
LARGO_MINIMO = 10

# Rutas que nunca piden código.
#   * /api/health   -> lo consulta Vercel y el arranque local.
#   * /api/acceso*  -> es la puerta misma.
#   * /api/catalogo -> tiene su propia X-API-Key para las apps externas
#                      (Apptender). Meterle también la cookie la rompería.
ABIERTAS = ("/api/health", "/api/acceso", "/api/catalogo")

# Métodos que modifican datos: en modo demo se rechazan.
ESCRITURA = ("POST", "PUT", "PATCH", "DELETE")


def _codigo(modo: str) -> str:
    """Código configurado para un modo. Vacío = ese modo no está habilitado."""
    if modo == MODO_DEMO:
        return os.getenv("ACCESO_CODIGO_DEMO", "")
    return os.getenv("ACCESO_CODIGO", "")


def _secreto() -> bytes:
    """Clave con la que se firman las cookies.

    Si no se define ACCESO_SECRETO se deriva del propio código. Consecuencia
    buscada: cambiar el código invalida todas las sesiones abiertas.
    """
    s = os.getenv("ACCESO_SECRETO") or _codigo(MODO_DUENO)
    return hashlib.sha256(s.encode()).digest()


def configurado() -> bool:
    return len(_codigo(MODO_DUENO)) >= LARGO_MINIMO


def _firmar(payload: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_secreto(), payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")


def crear_token(modo: str) -> str:
    """Token firmado: <payload_b64>.<firma>. No lleva el código adentro."""
    payload = json.dumps({"modo": modo, "exp": int(time.time()) + DURACION},
                         separators=(",", ":"))
    p64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{p64}.{_firmar(p64)}"


def modo_de_token(token: str | None) -> str | None:
    """Modo que acredita el token, o None si es inválido, ajeno o vencido."""
    if not token or "." not in token:
        return None
    p64, firma = token.rsplit(".", 1)
    # compare_digest: la comparación no debe filtrar en cuánto tarda.
    if not hmac.compare_digest(firma, _firmar(p64)):
        return None
    try:
        datos = json.loads(base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if datos.get("exp", 0) < time.time():
        return None
    modo = datos.get("modo")
    return modo if modo in (MODO_DUENO, MODO_DEMO) else None


def verificar_codigo(codigo: str) -> str | None:
    """Modo que abre ese código, o None si no abre nada."""
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    for modo in (MODO_DUENO, MODO_DEMO):
        esperado = _codigo(modo)
        if len(esperado) >= LARGO_MINIMO and hmac.compare_digest(codigo, esperado):
            return modo
    return None


def ruta_abierta(path: str) -> bool:
    return any(path.startswith(p) for p in ABIERTAS)


# --------------------------------------------------------------------------- #
# Freno de fuerza bruta
# --------------------------------------------------------------------------- #
# Se apoya en el Redis que ya usa el proyecto. Si no hay KV vivo NO se bloquea
# el acceso: el freno es una defensa extra, no la puerta. Que se caiga el KV no
# puede dejar al dueño por fuera.
MAX_INTENTOS = 10
VENTANA = 300  # segundos


def _redis():
    from homologacion_store import _redis_url, _redis  # import diferido
    return _redis() if _redis_url() else None


def intento_fallido(ip: str) -> None:
    try:
        r = _redis()
        if r:
            clave = f"acceso:intentos:{ip}"
            r.incr(clave)
            r.expire(clave, VENTANA)
    except Exception:
        pass


def bloqueado(ip: str) -> bool:
    try:
        r = _redis()
        if not r:
            return False
        return int(r.get(f"acceso:intentos:{ip}") or 0) >= MAX_INTENTOS
    except Exception:
        return False


def limpiar_intentos(ip: str) -> None:
    try:
        r = _redis()
        if r:
            r.delete(f"acceso:intentos:{ip}")
    except Exception:
        pass
