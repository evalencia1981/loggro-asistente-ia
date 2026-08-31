"""
catalogo_store.py
Homologación de la CARTA: mapa `código único de la app externa` -> `producto de Loggro`.

Es el gemelo del `homologacion_store.py` (que mapea descripciones de tirillas de
compra). Aquí el índice no es una descripción sino el **código único e inmutable**
que cada app (Apptender, etc.) le da a su producto: ese código es el contrato.
Mientras el código no cambie, el producto se puede renombrar, cambiar de precio o
desactivarse desde cualquier app y siempre se sabe a qué producto de Loggro apunta.

Por qué el código NO se guarda dentro de Loggro: se probó mandar `sku`, `code`,
`barCode`, `reference` y `externalIntegration.apptender` en POST /products y Loggro
los descarta (su esquema solo acepta `externalIntegration.rappi`). Por eso el mapa
vive aquí, en el mismo Redis/KV que ya usa la homologación de compras.

Estructura (clave KV "catalogo"):
{
  "version": 1,
  "apps": {
    "apptender": {
      "name": "Apptender",
      "items": {
        "APT-001": {
          "codigo": "APT-001",            # tal como lo mandó la app (sin normalizar)
          "product_id": "688d72...",      # _id en Loggro
          "product_name": "Cerveza Poker",
          "nombre_origen": "CERVEZA POKER",
          "creado_por_api": true,         # lo creamos nosotros vs. ya existía en Loggro
          "vinculado_at": "2026-07-28T...",
          "last_push": {"nombre": ..., "precio": ..., "activo": ..., "at": "..."}
        }
      }
    }
  }
}

`last_push` es la huella de lo último que ESTA API escribió en Loggro. Sirve para el
flujo inverso (Loggro -> app): si el estado actual del producto coincide con la
huella, el cambio es nuestro propio eco y no se reporta como cambio ajeno.
"""
from __future__ import annotations

import os
import json
import datetime as dt
from typing import Any

import homologacion_store as _kv

CATALOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo.json")


def _kv_key() -> str:
    """Clave del KV. `CATALOGO_KV_KEY` permite apuntar a un espacio aparte (pruebas)
    sin riesgo de tocar los vínculos reales."""
    return os.getenv("CATALOGO_KV_KEY", "catalogo")


def ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict[str, Any]:
    return {"version": 1, "apps": {}}


def normalizar_codigo(codigo: str) -> str:
    """Clave canónica del código externo: sin espacios, en mayúsculas.

    Se indexa en mayúsculas para que 'apt-001' y 'APT-001' sean el mismo producto;
    el código original se conserva en el campo `codigo` de la entrada.
    """
    return (codigo or "").strip().upper()


# --------------------------------------------------------------------------- #
# Persistencia (Redis/KV en prod, archivo JSON en desarrollo)
# --------------------------------------------------------------------------- #
def _archivo() -> dict[str, Any]:
    try:
        with open(CATALOGO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return _empty()


def cargar() -> dict[str, Any]:
    """Carga los vínculos código -> producto.

    Si el KV está configurado pero no responde, cae al archivo local en vez de
    fallar. "No responde" no es "está vacío": devolver vacío haría que las apps
    externas crean que sus productos no están vinculados y los vuelvan a crear.
    """
    if not _kv.kv_disponible():
        data = _archivo()
    else:
        try:
            raw = _kv.kv_get(_kv_key())
        except Exception as e:
            print(f"[catalogo] KV no responde ({e}); leyendo archivo local.")
            data = _archivo()
        else:
            if not raw:
                return _empty()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return _empty()
    if not isinstance(data, dict) or "apps" not in data:
        return _empty()
    return data


def guardar(data: dict[str, Any]) -> str:
    """Persiste los vínculos. Devuelve dónde quedó: "kv" o "local"."""
    payload = json.dumps(data, ensure_ascii=False)
    try:
        if _kv.kv_set(_kv_key(), payload):
            return "kv"
    except Exception as e:
        print(f"[catalogo] KV no responde al guardar ({e}); se escribe local.")
    try:
        with open(CATALOGO_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return "local"
    except OSError as e:
        raise RuntimeError(
            "No se pudo guardar el catálogo: el almacenamiento no es escribible y "
            "el Redis/KV no responde. Revisa REDIS_URL (o KV_REST_API_URL/"
            f"KV_REST_API_TOKEN) en el entorno. Detalle: {e}"
        ) from e


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #
def app_items(app_id: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Todos los vínculos de una app: {CODIGO: entrada}."""
    data = data if data is not None else cargar()
    return (data["apps"].get(app_id) or {}).get("items", {})


def vinculo(app_id: str, codigo: str, data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """La entrada del código, o None si aún no está homologado."""
    return app_items(app_id, data).get(normalizar_codigo(codigo))


def por_product_id(app_id: str, data: dict[str, Any] | None = None) -> dict[str, str]:
    """Índice inverso {product_id de Loggro: CODIGO externo} para el flujo Loggro -> app."""
    return {e["product_id"]: cod for cod, e in app_items(app_id, data).items() if e.get("product_id")}


def product_ids_ocupados(data: dict[str, Any] | None = None) -> dict[str, str]:
    """{product_id: 'app/codigo'} de TODAS las apps: evita vincular dos códigos al mismo producto."""
    data = data if data is not None else cargar()
    ocupados: dict[str, str] = {}
    for app_id, app in data["apps"].items():
        for cod, e in (app.get("items") or {}).items():
            if e.get("product_id"):
                ocupados[e["product_id"]] = f"{app_id}/{cod}"
    return ocupados


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #
def vincular(app_id: str, app_name: str, codigo: str, product_id: str,
             product_name: str | None = None, nombre_origen: str | None = None,
             creado_por_api: bool = False, data: dict[str, Any] | None = None,
             persistir: bool = True) -> dict[str, Any]:
    """Crea/actualiza el vínculo código externo -> producto de Loggro."""
    data = data if data is not None else cargar()
    app = data["apps"].setdefault(app_id, {"name": app_name or app_id, "items": {}})
    if app_name:
        app["name"] = app_name
    key = normalizar_codigo(codigo)
    previo = app["items"].get(key) or {}
    app["items"][key] = {
        **previo,
        "codigo": (codigo or "").strip(),
        "product_id": product_id,
        "product_name": product_name,
        "nombre_origen": nombre_origen if nombre_origen is not None else previo.get("nombre_origen"),
        "creado_por_api": creado_por_api or previo.get("creado_por_api", False),
        "vinculado_at": previo.get("vinculado_at") or ahora(),
    }
    if persistir:
        guardar(data)
    return data


def desvincular(app_id: str, codigo: str, data: dict[str, Any] | None = None,
                persistir: bool = True) -> dict[str, Any]:
    """Quita el vínculo (no toca el producto en Loggro)."""
    data = data if data is not None else cargar()
    app = data["apps"].get(app_id)
    if app:
        app["items"].pop(normalizar_codigo(codigo), None)
        if persistir:
            guardar(data)
    return data


def marcar_push(app_id: str, codigo: str, nombre: str | None, precio: float | None,
                activo: bool | None, product_name: str | None = None,
                data: dict[str, Any] | None = None, persistir: bool = True) -> dict[str, Any]:
    """Registra lo último que esta API escribió en Loggro (huella anti-eco)."""
    data = data if data is not None else cargar()
    entrada = (data["apps"].get(app_id) or {}).get("items", {}).get(normalizar_codigo(codigo))
    if entrada is not None:
        entrada["last_push"] = {"nombre": nombre, "precio": precio,
                                "activo": activo, "at": ahora()}
        if product_name:
            entrada["product_name"] = product_name
        if persistir:
            guardar(data)
    return data
