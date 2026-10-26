"""
usuarios_store.py
Usuarios de la app: quién entra, con qué rol y si sigue activo.

Estructura (usuarios.json o la clave "usuarios" del KV):
{
  "version": 1,
  "items": {
    "<usuario>": {
      "nombre": "Simón",
      "rol": "bodega",                  # ver acceso.ROLES
      "activo": true,
      "hash": "<scrypt hex>", "sal": "<hex>",
      "sesion": 3,                      # sube al cambiar clave/rol o desactivar
      "creado": "2026-10-26T…", "ultimo_ingreso": "2026-10-26T…"
    }
  },
  "roles": {"admin": ["compras", "stock", …]}   # módulos elegidos por el dueño
}

`roles` solo guarda lo que el dueño cambió; un rol que no aparece usa los
módulos por defecto de acceso.ROLES.

Por qué `sesion`: la cookie dura 30 días y está firmada, así que sin algo que
la invalide, desactivar a alguien no lo sacaría hasta que venza. Cada token
lleva el número de sesión con el que se emitió; si ya no coincide, no vale.

Las contraseñas se guardan con scrypt (stdlib) y sal propia. Nunca salen de
aquí: `publico()` es lo único que se le devuelve al frontend.
"""
from __future__ import annotations

import os
import re
import json
import hmac
import time
import hashlib
import secrets
import datetime as dt
from typing import Any

from homologacion_store import kv_disponible, kv_get, kv_set

USUARIOS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usuarios.json")
_KV_KEY = "usuarios"

CLAVE_MINIMA = 8
_USUARIO_VALIDO = re.compile(r"^[a-z0-9._-]{3,32}$")

# scrypt: ~50 ms por intento. Suficiente para que la fuerza bruta no sea
# práctica, sin volver lento el login en una función de Vercel.
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

# El middleware consulta el usuario en CADA petición (para que desactivar sea
# inmediato). Una caché corta evita un GET a Redis por cada llamada.
_CACHE_TTL = 15
_cache: dict[str, Any] = {"t": 0.0, "data": None}


def _empty() -> dict[str, Any]:
    return {"version": 1, "items": {}, "roles": {}}


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _hash(clave: str, sal: bytes) -> str:
    return hashlib.scrypt(clave.encode(), salt=sal, **_SCRYPT).hex()


def normalizar_usuario(usuario: str) -> str:
    return (usuario or "").strip().lower()


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #
def _archivo() -> dict[str, Any]:
    try:
        with open(USUARIOS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return _empty()


def cargar(usar_cache: bool = False) -> dict[str, Any]:
    """Redis/KV si está configurado; si no (o si no responde), el archivo local.

    Si el KV se cae en producción no hay archivo local: quedan cero usuarios y
    solo entra el código maestro. Falla cerrado, que es lo correcto aquí.
    """
    if usar_cache and _cache["data"] is not None and time.time() - _cache["t"] < _CACHE_TTL:
        return _cache["data"]
    data: Any
    if not kv_disponible():
        data = _archivo()
    else:
        try:
            raw = kv_get(_KV_KEY)
            data = json.loads(raw) if raw else _empty()
        except Exception as e:
            print(f"[usuarios] KV no responde ({e}); leyendo archivo local.")
            data = _archivo()
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        data = _empty()
    if not isinstance(data.get("roles"), dict):
        data["roles"] = {}
    _cache.update(t=time.time(), data=data)
    return data


def guardar(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    _cache.update(t=time.time(), data=data)
    try:
        if kv_set(_KV_KEY, payload):
            return "kv"
    except Exception as e:
        print(f"[usuarios] KV no responde al guardar ({e}); se escribe local.")
    try:
        with open(USUARIOS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return "local"
    except OSError as e:
        raise RuntimeError(
            "No se pudo guardar el usuario: el almacenamiento no es escribible y el "
            f"Redis/KV no responde. Revisa REDIS_URL. ({e})"
        ) from e


# --------------------------------------------------------------------------- #
# Operaciones
# --------------------------------------------------------------------------- #
def publico(usuario: str, u: dict[str, Any]) -> dict[str, Any]:
    """Lo que el frontend puede ver de un usuario (sin hash ni sal)."""
    return {
        "usuario": usuario,
        "nombre": u.get("nombre") or usuario,
        "rol": u.get("rol"),
        "activo": bool(u.get("activo", True)),
        "creado": u.get("creado"),
        "ultimo_ingreso": u.get("ultimo_ingreso"),
    }


def listar() -> list[dict[str, Any]]:
    items = cargar()["items"]
    return sorted((publico(k, v) for k, v in items.items()),
                  key=lambda u: (not u["activo"], u["nombre"].lower()))


def obtener(usuario: str, usar_cache: bool = False) -> dict[str, Any] | None:
    return cargar(usar_cache)["items"].get(normalizar_usuario(usuario))


def _validar_clave(clave: str) -> None:
    if len(clave or "") < CLAVE_MINIMA:
        raise ValueError(f"La contraseña debe tener al menos {CLAVE_MINIMA} caracteres.")


def crear(usuario: str, nombre: str, rol: str, clave: str) -> dict[str, Any]:
    usuario = normalizar_usuario(usuario)
    if not _USUARIO_VALIDO.match(usuario):
        raise ValueError("El usuario debe tener 3 a 32 caracteres: letras, números, punto, guion.")
    _validar_clave(clave)
    data = cargar()
    if usuario in data["items"]:
        raise ValueError(f"Ya existe el usuario '{usuario}'.")
    sal = secrets.token_bytes(16)
    data["items"][usuario] = {
        "nombre": (nombre or "").strip() or usuario,
        "rol": rol,
        "activo": True,
        "hash": _hash(clave, sal),
        "sal": sal.hex(),
        "sesion": 1,
        "creado": _ahora(),
        "ultimo_ingreso": None,
    }
    guardar(data)
    return publico(usuario, data["items"][usuario])


def actualizar(usuario: str, *, nombre: str | None = None, rol: str | None = None,
               activo: bool | None = None, clave: str | None = None) -> dict[str, Any]:
    """Cambia datos de un usuario. Rol, estado o clave nuevos cierran sus sesiones."""
    usuario = normalizar_usuario(usuario)
    data = cargar()
    u = data["items"].get(usuario)
    if u is None:
        raise KeyError(usuario)
    cerrar_sesiones = False
    if nombre is not None and nombre.strip():
        u["nombre"] = nombre.strip()
    if rol is not None and rol != u.get("rol"):
        u["rol"] = rol
        cerrar_sesiones = True
    if activo is not None and activo != u.get("activo", True):
        u["activo"] = activo
        cerrar_sesiones = True
    if clave:
        _validar_clave(clave)
        sal = secrets.token_bytes(16)
        u["hash"], u["sal"] = _hash(clave, sal), sal.hex()
        cerrar_sesiones = True
    if cerrar_sesiones:
        u["sesion"] = int(u.get("sesion") or 1) + 1
    guardar(data)
    return publico(usuario, u)


def verificar(usuario: str, clave: str) -> tuple[str, dict[str, Any]] | None:
    """(usuario, datos) si la clave es correcta y el usuario está activo."""
    usuario = normalizar_usuario(usuario)
    u = cargar()["items"].get(usuario)
    if u is None:
        # Se calcula un hash igual: que "no existe" y "clave mala" tarden lo mismo
        # y no se pueda averiguar qué usuarios existen.
        _hash(clave or "", b"\0" * 16)
        return None
    ok = hmac.compare_digest(_hash(clave or "", bytes.fromhex(u.get("sal") or "")), u.get("hash") or "")
    if not ok or not u.get("activo", True):
        return None
    return usuario, u


def registrar_ingreso(usuario: str) -> None:
    """Fecha del último ingreso. Si falla, no impide entrar."""
    try:
        data = cargar()
        u = data["items"].get(normalizar_usuario(usuario))
        if u is not None:
            u["ultimo_ingreso"] = _ahora()
            guardar(data)
    except Exception as e:
        print(f"[usuarios] no se pudo registrar el ingreso ({e}).")


# --------------------------------------------------------------------------- #
# Módulos por rol (los elige el dueño)
# --------------------------------------------------------------------------- #
def modulos_de_rol(rol: str, usar_cache: bool = False) -> list[str] | None:
    """Módulos que el dueño eligió para el rol, o None si usa los de por defecto."""
    v = cargar(usar_cache)["roles"].get(rol)
    return list(v) if isinstance(v, list) else None


def guardar_modulos_de_rol(rol: str, modulos: list[str]) -> list[str]:
    data = cargar()
    data["roles"][rol] = list(modulos)
    guardar(data)
    return list(modulos)
