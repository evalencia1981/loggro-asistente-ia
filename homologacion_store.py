"""
homologacion_store.py
Almacén de homologación indexado por **proveedor + descripción de tirilla**.

Estructura del archivo (homologacion.json):
{
  "version": 2,
  "providers": {
    "<provider_id>": {
      "name": "<nombre legible>",
      "items": {
        "<DESCRIPCION TIRILLA EN MAYUS>": { "product_id": "...", "product_name": "..." }
      }
    }
  }
}

Por qué por proveedor: el mismo producto se llama distinto según el proveedor.
La homologación "aprende": se pregunta solo cuando no reconoce un ítem; al asignarlo
queda guardado y no se vuelve a preguntar.
"""
from __future__ import annotations

import os
import re
import json
from typing import Any

import requests

HOMOLOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homologacion.json")

# --------------------------------------------------------------------------- #
# Backend de almacenamiento (en orden de preferencia):
#   1. Redis por cadena de conexión  -> REDIS_URL / KV_URL (rediss://...). Es lo
#      que expone la integración Redis de Vercel/Upstash.
#   2. KV REST (Upstash/Vercel KV)   -> KV_REST_API_URL/TOKEN o UPSTASH_*.
#   3. Archivo JSON local            -> solo en desarrollo (FS escribible).
# --------------------------------------------------------------------------- #
_KV_KEY = "homologacion"


# ---- 1. Redis por cadena de conexión (REDIS_URL) ---- #
def _redis_url() -> str:
    return os.getenv("REDIS_URL") or os.getenv("KV_URL") or ""


_redis_client = None


def _redis():
    """Cliente Redis (cacheado por instancia). Import diferido: solo si hay REDIS_URL."""
    global _redis_client
    if _redis_client is None:
        import redis  # type: ignore
        _redis_client = redis.from_url(_redis_url(), decode_responses=True)
    return _redis_client


# ---- 2. KV REST (Upstash/Vercel KV) ---- #
def _kv_creds() -> tuple[str, str]:
    """Resuelve URL/token del KV REST. Acepta los nombres de Vercel KV y de Upstash."""
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or ""
    token = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
    return url, token


def _kv_rest_enabled() -> bool:
    url, token = _kv_creds()
    return bool(url and token)


def _kv_cmd(cmd: list) -> Any:
    """Ejecuta un comando Redis vía la API REST de Upstash/Vercel KV."""
    url, token = _kv_creds()
    r = requests.post(url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                      json=cmd, timeout=15)
    r.raise_for_status()
    return r.json().get("result")


# ---- Acceso genérico al KV (lo reutiliza catalogo_store.py) ---- #
def kv_disponible() -> bool:
    """True si hay un almacén remoto (Redis o KV REST); False = solo archivo local."""
    return bool(_redis_url() or _kv_rest_enabled())


def kv_get(key: str) -> str | None:
    """Lee una clave del KV. None si no hay KV configurado o la clave no existe."""
    if _redis_url():
        return _redis().get(key)
    if _kv_rest_enabled():
        return _kv_cmd(["GET", key])
    return None


def kv_set(key: str, payload: str) -> bool:
    """Escribe una clave en el KV. False si no hay KV (el llamador usa archivo local)."""
    if _redis_url():
        _redis().set(key, payload)
        return True
    if _kv_rest_enabled():
        _kv_cmd(["SET", key, payload])
        return True
    return False

# Código consecutivo de facturación al inicio de la descripción (ej. "000474").
# Cambia entre facturas, así que NO debe afectar la homologación: lo quitamos.
# 4+ dígitos para no comerse volúmenes legítimos como "355ML".
_CODIGO_INICIAL = re.compile(r"^\s*\d{4,}\s*")


def _empty() -> dict[str, Any]:
    return {"version": 2, "providers": {}}


def _normalizar(desc: str) -> str:
    """Clave canónica de una descripción: sin código inicial, sin espacios extra, MAYÚS."""
    s = (desc or "").strip().upper()
    s = _CODIGO_INICIAL.sub("", s)        # quita el consecutivo del proveedor
    s = re.sub(r"\s+", " ", s).strip()    # colapsa espacios múltiples
    return s


# Alias público para reutilizar la misma normalización fuera del módulo.
normalizar = _normalizar


def _migrar(data: Any) -> dict[str, Any]:
    """Normaliza a v2; migra el formato antiguo plano {desc: id} si hace falta."""
    if isinstance(data, dict) and data.get("version") == 2:
        return data
    migrado = _empty()
    items = {
        _normalizar(desc): {"product_id": pid, "product_name": None}
        for desc, pid in (data or {}).items()
    }
    if items:
        migrado["providers"]["_heredado"] = {"name": "Sin proveedor (heredado)", "items": items}
    return migrado


def cargar(path: str | None = None) -> dict[str, Any]:
    """Carga el almacén. Migra formato antiguo a v2.

    Sin `path`: Redis/KV si está configurado (producción), si no el archivo local.
    Con `path` explícito: SIEMPRE ese archivo, aunque haya Redis. Pasar una ruta y
    que el dato saliera de Redis era una trampa: el llamador creía estar trabajando
    contra un archivo de pruebas y estaba tocando producción.
    """
    if path is not None or not kv_disponible():
        try:
            with open(path or HOMOLOG_PATH, encoding="utf-8") as f:
                return _migrar(json.load(f))
        except FileNotFoundError:
            return _empty()

    raw = kv_get(_KV_KEY)
    if not raw:
        return _empty()
    try:
        return _migrar(json.loads(raw))
    except (json.JSONDecodeError, TypeError):
        return _empty()


def guardar(data: dict[str, Any], path: str | None = None) -> None:
    """Persiste el almacén.

    Sin `path`: Redis/KV si está configurado (producción), si no el archivo local.
    Con `path` explícito: SIEMPRE ese archivo, nunca Redis (ver `cargar`).
    """
    payload = json.dumps(data, ensure_ascii=False)
    if path is None and kv_set(_KV_KEY, payload):
        return
    try:
        with open(path or HOMOLOG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        # En Vercel el filesystem es de solo lectura: sin Redis/KV no hay dónde persistir.
        # Mensaje explícito para no fallar en silencio (antes el tap "no seleccionaba").
        raise RuntimeError(
            "No se pudo guardar la homologación: el almacenamiento no es escribible "
            "y no hay Redis/KV configurado. Define REDIS_URL (o KV_REST_API_URL/"
            f"KV_REST_API_TOKEN) en el entorno. Detalle: {e}"
        ) from e


def resolver(provider_id: str, descripcion: str, data: dict[str, Any] | None = None) -> str | None:
    """Devuelve product_id si (proveedor, descripcion) ya está homologado; si no, None."""
    data = data if data is not None else cargar()
    prov = data["providers"].get(provider_id)
    if not prov:
        return None
    entry = prov["items"].get(_normalizar(descripcion))
    return entry["product_id"] if entry else None


def asignar(provider_id: str, provider_name: str, descripcion: str,
            product_id: str, product_name: str | None = None, factor: float = 1,
            data: dict[str, Any] | None = None, persistir: bool = True) -> dict[str, Any]:
    """Crea/actualiza el símil de un ítem para un proveedor y persiste el cambio.

    `factor` = unidades de inventario por cada unidad facturada (ej. un six pack = 6).
    """
    data = data if data is not None else cargar()
    prov = data["providers"].setdefault(provider_id, {"name": provider_name or "", "items": {}})
    if provider_name:
        prov["name"] = provider_name
    prov["items"][_normalizar(descripcion)] = {
        "product_id": product_id,
        "product_name": product_name,
        "factor": factor or 1,
    }
    if persistir:
        guardar(data)
    return data


def eliminar(provider_id: str, descripcion: str, data: dict[str, Any] | None = None,
             persistir: bool = True) -> dict[str, Any]:
    """Quita un símil (por si se asignó mal)."""
    data = data if data is not None else cargar()
    prov = data["providers"].get(provider_id)
    if prov:
        prov["items"].pop(_normalizar(descripcion), None)
        if persistir:
            guardar(data)
    return data
