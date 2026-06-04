"""
loggro_intake.schema — Esquema estable de una factura de compra (sección 4.1 del spec).

Es el contrato común que producen tanto el extractor de imágenes como el chat.
Compatible con responseSchema de Gemini (subconjunto de OpenAPI: SIN additionalProperties).
"""
from __future__ import annotations

# Esquema de la factura extraída. Todos los `required` listados; los campos que no
# aparezcan se rellenan con "" (texto) o 0 (número).
FACTURA_SCHEMA = {
    "type": "object",
    "properties": {
        "proveedor": {
            "type": "object",
            "properties": {
                "nombre_tirilla": {"type": "string"},
                "nit": {"type": "string"},
            },
            "required": ["nombre_tirilla", "nit"],
        },
        "documento": {
            "type": "object",
            "properties": {
                "numero": {"type": "string"},
                "tipo": {"type": "string"},
                "forma_pago": {"type": "string"},
                "pagado": {"type": "boolean"},
                "fecha": {"type": "string"},
            },
            "required": ["numero", "tipo", "forma_pago", "pagado", "fecha"],
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cod_proveedor": {"type": "string"},
                    "descripcion": {"type": "string"},
                    "um": {"type": "string"},
                    "cantidad": {"type": "number"},
                    "total": {"type": "number"},
                    "base": {"type": "number"},
                    "iva_pct": {"type": "number"},
                    "iva": {"type": "number"},
                    "ic_licores": {"type": "number"},
                },
                "required": ["descripcion", "cantidad", "total"],
            },
        },
        "totales": {
            "type": "object",
            "properties": {
                "base": {"type": "number"},
                "iva": {"type": "number"},
                "ic_licores": {"type": "number"},
                "total_pagar": {"type": "number"},
            },
            "required": ["total_pagar"],
        },
        "cuadra": {"type": "boolean"},
    },
    "required": ["proveedor", "documento", "items", "totales", "cuadra"],
}

MEDIA_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp",
}


def media_type_from_name(filename: str) -> str:
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    return MEDIA_TYPES.get(ext, "image/jpeg")
