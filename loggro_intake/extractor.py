"""
loggro_intake.extractor — Extracción de facturas/tirillas desde imagen (visión).

Recibe los bytes de una foto y devuelve el dict de la factura (FACTURA_SCHEMA).
"""
from __future__ import annotations

import base64

from .schema import FACTURA_SCHEMA, media_type_from_name  # noqa: F401 (re-export)
from .gemini import generar_json

PROMPT = """Eres un experto en lectura de tirillas y facturas de compra de un bar/restaurante en Colombia.
Extrae los datos de la imagen al esquema JSON indicado. Reglas:
- Una línea por producto en `items`, con la `descripcion` en MAYÚSCULAS.
- Si la línea trae un código de producto al inicio (ej. "000474", suele ser un consecutivo del proveedor), ponlo en `cod_proveedor` y NO lo incluyas en `descripcion`. La `descripcion` es SOLO el nombre del producto (ej. "POKER 330ML").
- `cantidad` y `total` (valor total de la línea, con impuestos) son obligatorios por línea.
- Si un campo numérico no aparece, usa 0. Si un texto no aparece, usa "".
- `nit` del proveedor sin puntos ni guiones si es posible.
- `total_pagar` es el total final de la factura.
- `cuadra` = true si la suma de los `total` de las líneas coincide con `total_pagar`.
- No inventes datos: si algo no es legible, déjalo en 0 o "".
Devuelve solo el JSON del esquema."""


def extraer_tirilla(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Llama a Gemini con la imagen y devuelve el dict de la factura (sección 4.1)."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    parts = [
        {"inline_data": {"mime_type": media_type, "data": b64}},
        {"text": PROMPT},
    ]
    return generar_json(parts, FACTURA_SCHEMA)
