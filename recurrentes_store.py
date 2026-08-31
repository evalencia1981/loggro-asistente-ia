"""
recurrentes_store.py
Almacén de **beneficiarios recurrentes** de gastos (nómina, pagos fijos…).

Estructura del archivo (recurrentes.json):
{
  "version": 1,
  "items": {
    "<slug>": {
      "nombre": "Simón",
      "concepto": "Nómina Simón",
      "type_expense_id": "...",
      "provider_id": null,
      "forma_pago": "efectivo",
      "sale_de_caja": false,
      "monto_sugerido": 60000,
      "periodicidad": "semanal|quincenal|mensual|libre",
      "activo": true,
      "ultimo_pago": "2026-08-23",
      "notas": ""
    }
  }
}

Por qué existe: en el historial de Loggro el mismo pago a la misma persona
aparece escrito de seis formas ("Nomina Simon", "simon nomina 09/05", "Pago
simon"…), lo que hace imposible totalizar por persona. Lo recurrente aquí NO es
el monto ni la fecha —los montos de un mismo beneficiario van de 25.500 a
144.500— sino el beneficiario. Así que se guarda lo que no cambia (concepto
normalizado y tipo de gasto) y el monto se digita en cada pago.

La periodicidad es solo informativa: sirve para ordenar la lista y avisar
"hace 12 días", nunca para crear un gasto solo.
"""
from __future__ import annotations

import os
import re
import json
import unicodedata
from typing import Any

# El acceso al KV (Redis / KV REST / archivo local) ya está resuelto ahí; se
# reutiliza tal cual para no tener dos implementaciones del mismo almacenamiento.
from homologacion_store import kv_disponible, kv_get, kv_set

RECURRENTES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "recurrentes.json"
)

_KV_KEY = "recurrentes"

PERIODICIDADES = ("semanal", "quincenal", "mensual", "libre")

# Días nominales de cada periodicidad, para calcular si un pago está "vencido".
DIAS_PERIODO = {"semanal": 7, "quincenal": 15, "mensual": 30}


def _empty() -> dict[str, Any]:
    return {"version": 1, "items": {}}


def slugify(nombre: str) -> str:
    """Clave estable a partir del nombre: sin tildes, minúsculas, guiones.

    Se usa como id del beneficiario para que renombrar "Simón" -> "Simon" no
    cree un duplicado.
    """
    s = unicodedata.normalize("NFKD", (nombre or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "sin-nombre"


def _archivo(path: str | None) -> dict[str, Any]:
    try:
        with open(path or RECURRENTES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return _empty()


def cargar(path: str | None = None) -> dict[str, Any]:
    """Carga el almacén.

    Sin `path`: Redis/KV si está configurado (producción), si no el archivo local.
    Con `path` explícito: SIEMPRE ese archivo, aunque haya Redis (mismo criterio
    que homologacion_store: pasar una ruta y leer de producción era una trampa).

    Si el KV está configurado pero no responde, se lee el archivo local en vez
    de fallar: para *mostrar* la lista, un dato viejo sirve más que un error.
    Guardar sí avisa (ver `guardar`), porque ahí sí se puede perder algo.
    """
    if path is not None or not kv_disponible():
        data = _archivo(path)
    else:
        try:
            raw = kv_get(_KV_KEY)
        except Exception as e:
            print(f"[recurrentes] KV no responde ({e}); leyendo archivo local.")
            data = _archivo(None)
        else:
            if not raw:
                return _empty()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return _empty()

    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return _empty()
    data.setdefault("version", 1)
    return data


def guardar(data: dict[str, Any], path: str | None = None) -> str:
    """Persiste el almacén. Devuelve dónde quedó: "kv" o "local".

    El valor de retorno importa: si el KV está configurado y falla, el dato se
    escribe local para no perderlo, pero el llamador debe poder avisar que ese
    guardado NO viajó a producción. Devolver "local" cuando se esperaba "kv" es
    la señal de que el almacén remoto está caído.
    """
    payload = json.dumps(data, ensure_ascii=False)
    if path is None:
        try:
            if kv_set(_KV_KEY, payload):
                return "kv"
        except Exception as e:
            print(f"[recurrentes] KV no responde al guardar ({e}); se escribe local.")
    try:
        with open(path or RECURRENTES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return "local"
    except OSError as e:
        # En Vercel el filesystem es de solo lectura: sin KV vivo no hay dónde
        # persistir y hay que decirlo, no fallar en silencio.
        raise RuntimeError(
            "No se pudieron guardar los recurrentes: el almacenamiento no es "
            "escribible y el Redis/KV no responde. Revisa REDIS_URL (o "
            f"KV_REST_API_URL/KV_REST_API_TOKEN) en el entorno. Detalle: {e}"
        ) from e


def listar(data: dict[str, Any] | None = None, incluir_inactivos: bool = False) -> list[dict]:
    """Beneficiarios como lista, cada uno con su `id`. Ordenados por nombre."""
    data = data if data is not None else cargar()
    filas = [
        {**v, "id": slug}
        for slug, v in data["items"].items()
        if incluir_inactivos or v.get("activo", True)
    ]
    filas.sort(key=lambda r: (r.get("nombre") or "").lower())
    return filas


def guardar_item(item: dict[str, Any], data: dict[str, Any] | None = None,
                 persistir: bool = True) -> tuple[str, dict[str, Any], str | None]:
    """Crea o actualiza un beneficiario. Devuelve (id, almacén, dónde se guardó).

    El `id` viene del propio item si se está editando; si no, se deriva del
    nombre. El concepto por defecto es el nombre: es el texto que se escribirá
    igual en todos los gastos de esa persona.
    """
    data = data if data is not None else cargar()
    nombre = (item.get("nombre") or "").strip()
    if not nombre:
        raise ValueError("El nombre del beneficiario es obligatorio.")
    if not item.get("type_expense_id"):
        raise ValueError("El tipo de gasto es obligatorio.")

    slug = (item.get("id") or "").strip() or slugify(nombre)
    periodicidad = item.get("periodicidad") or "libre"
    if periodicidad not in PERIODICIDADES:
        periodicidad = "libre"

    previo = data["items"].get(slug, {})
    data["items"][slug] = {
        "nombre": nombre,
        "concepto": (item.get("concepto") or "").strip() or nombre,
        "type_expense_id": item["type_expense_id"],
        "provider_id": item.get("provider_id") or None,
        "forma_pago": (item.get("forma_pago") or "").strip(),
        "sale_de_caja": bool(item.get("sale_de_caja")),
        "monto_sugerido": int(item.get("monto_sugerido") or 0),
        "periodicidad": periodicidad,
        "activo": bool(item.get("activo", True)),
        "notas": (item.get("notas") or "").strip(),
        # El último pago lo escribe el registro de gastos, no el formulario:
        # así editar un beneficiario nunca borra su historial.
        "ultimo_pago": previo.get("ultimo_pago"),
    }
    donde = guardar(data) if persistir else None
    return slug, data, donde


def eliminar(slug: str, data: dict[str, Any] | None = None,
             persistir: bool = True) -> tuple[dict[str, Any], str | None]:
    """Quita un beneficiario de la lista. Devuelve (almacén, dónde se guardó)."""
    data = data if data is not None else cargar()
    data["items"].pop(slug, None)
    donde = guardar(data) if persistir else None
    return data, donde


def marcar_pago(slug: str, fecha: str, monto: int, data: dict[str, Any] | None = None,
                persistir: bool = True) -> dict[str, Any]:
    """Registra que a este beneficiario se le pagó, para el aviso de 'hace N días'.

    El monto pagado pasa a ser el sugerido: en la práctica lo que más se repite
    es el último valor, no un promedio.
    """
    data = data if data is not None else cargar()
    item = data["items"].get(slug)
    if not item:
        return data
    item["ultimo_pago"] = fecha
    if monto > 0:
        item["monto_sugerido"] = int(monto)
    if persistir:
        guardar(data)
    return data
