"""
loggro_intake.chat — Captura de facturas por conversación (lenguaje natural / dictado).

El usuario describe la factura hablando o escribiendo ("factura de Donde el Calvo,
30 pokers a 68.700, 30 pilsen a 75.870…") y, turno a turno, se va construyendo el
mismo dict de factura (FACTURA_SCHEMA). Mantiene estado: se le pasa la factura actual
y el mensaje nuevo, y devuelve la factura actualizada + una respuesta breve para el chat.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .schema import FACTURA_SCHEMA
from .gemini import generar_json

# La respuesta del chat: la factura completa actualizada + un mensaje corto al usuario.
CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "factura": FACTURA_SCHEMA,
        "respuesta": {"type": "string"},
    },
    "required": ["factura", "respuesta"],
}

SYSTEM = """Eres un asistente que ayuda a registrar facturas de compra de un bar/restaurante en Colombia conversando.
Recibes (1) el ESTADO ACTUAL de la factura en JSON y (2) el MENSAJE nuevo del usuario (puede venir de voz dictada, con errores).
Tu trabajo: actualizar la factura según el mensaje y devolver la factura COMPLETA actualizada + una `respuesta` breve y natural en español.

Reglas:
- Interpreta cantidades y precios dictados: "treinta pokers a sesenta y ocho mil setecientos" → cantidad 30, total de la línea 30*68700. Si el usuario da precio UNITARIO, multiplica por la cantidad para `total` (total de la línea con impuestos). Si da el total de la línea, úsalo tal cual.
- Descripción de cada ítem en MAYÚSCULAS, como se diría en una tirilla (ej. "POKER 330ML" si lo menciona, o "POKER" si no da más detalle).
- Permite agregar, modificar o eliminar ítems en mensajes sucesivos, y fijar proveedor (nombre y NIT), número de factura, fecha, si está pagada y forma de pago.
- Recalcula `totales.total_pagar` como la suma de los `total` de las líneas, salvo que el usuario indique un total distinto explícitamente.
- `cuadra` = true si la suma de las líneas coincide con `total_pagar`.
- Si un dato no se ha dicho, déjalo en "" o 0; NO inventes proveedores, NITs ni precios.
- La `respuesta` debe ser corta: confirma lo que entendiste y, si falta algo clave (proveedor o algún precio), pídelo amablemente.
- Mantén lo que ya estaba en el estado actual salvo que el usuario lo cambie.
Devuelve solo el JSON del esquema (factura + respuesta)."""


def _factura_vacia() -> dict[str, Any]:
    return {
        "proveedor": {"nombre_tirilla": "", "nit": ""},
        "documento": {"numero": "", "tipo": "", "forma_pago": "", "pagado": False, "fecha": ""},
        "items": [],
        "totales": {"total_pagar": 0},
        "cuadra": True,
    }


def conversar_doc(mensaje: str, doc_schema: dict, system_prompt: str,
                  estado: Optional[dict] = None, historial: Optional[list[dict]] = None,
                  etiqueta_doc: str = "DOCUMENTO") -> dict:
    """Genérico: un turno de chat que construye/actualiza un documento que cumple `doc_schema`.

    Devuelve {"data": <dict del documento>, "respuesta": <str>}. Reutilizable para
    factura, gasto, etc. pasando el esquema y el system prompt adecuados.
    """
    wrap_schema = {
        "type": "object",
        "properties": {"data": doc_schema, "respuesta": {"type": "string"}},
        "required": ["data", "respuesta"],
    }
    lineas_hist = ""
    if historial:
        lineas_hist = "\n".join(
            f"{h.get('role', 'user')}: {h.get('content', '')}" for h in historial[-8:]
        )
    prompt = (
        f"{system_prompt}\n\n"
        f"ESTADO ACTUAL DEL {etiqueta_doc} (JSON):\n{json.dumps(estado or {}, ensure_ascii=False)}\n\n"
        + (f"CONVERSACIÓN PREVIA:\n{lineas_hist}\n\n" if lineas_hist else "")
        + f"MENSAJE NUEVO DEL USUARIO:\n{mensaje}"
    )
    return generar_json([{"text": prompt}], wrap_schema)


def conversar(mensaje: str, factura: Optional[dict] = None,
              historial: Optional[list[dict]] = None) -> dict:
    """Factura (preset): un turno de chat. Devuelve {"factura": ..., "respuesta": ...}."""
    out = conversar_doc(
        mensaje, FACTURA_SCHEMA, SYSTEM,
        estado=factura or _factura_vacia(), historial=historial, etiqueta_doc="FACTURA",
    )
    return {"factura": out.get("data") or _factura_vacia(), "respuesta": out.get("respuesta", "")}
