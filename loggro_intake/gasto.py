"""
loggro_intake.gasto — Preset de captura de GASTOS (imagen o chat).

Extrae los datos que la IA puede leer de un recibo/factura de gasto. El tipo de
gasto y el responsable NO se extraen (son selecciones del usuario en Loggro).
Esquema alineado con el formulario de gasto de Loggro (POST /expenses).
"""
from __future__ import annotations

from typing import Optional

from .extractor import extraer_imagen
from .chat import conversar_doc

# Datos que la IA puede leer del documento. Compatible con responseSchema de Gemini.
GASTO_SCHEMA = {
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
                "fecha": {"type": "string"},
            },
            "required": ["numero", "fecha"],
        },
        "concepto": {"type": "string"},
        "forma_pago": {"type": "string"},
        "subtotal": {"type": "number"},
        "impuestos": {"type": "number"},
        # Pistas en texto libre (el usuario las dicta); el backend las cruza con los catálogos.
        "tipo_gasto": {"type": "string"},
        "responsable": {"type": "string"},
    },
    "required": ["proveedor", "documento", "concepto", "subtotal", "impuestos"],
}

PROMPT_IMG = """Eres un experto en lectura de facturas/recibos de GASTOS de un negocio en Colombia.
Extrae los datos de la imagen al esquema JSON indicado. Reglas:
- `concepto`: descripción corta del gasto (ej. "Arriendo local", "Servicios públicos", "Compra papelería").
- `subtotal`: valor base (sin impuestos). `impuestos`: total de impuestos (IVA, etc.). Si no se distinguen, pon todo en `subtotal` e `impuestos` en 0.
- `nit` del proveedor sin puntos ni guiones si es posible.
- `forma_pago`: como aparezca (efectivo, transferencia, tarjeta, crédito…); si no aparece, "".
- `tipo_gasto`: categoría si se infiere (ej. "arriendo", "nómina", "servicios públicos"); si no, "".
- `responsable`: nombre de la persona si aparece; si no, "".
- Si un campo numérico no aparece, usa 0. Si un texto no aparece, usa "".
- No inventes datos.
Devuelve solo el JSON del esquema."""

SYSTEM_CHAT = """Eres un asistente que ayuda a registrar GASTOS de un negocio en Colombia conversando.
Recibes (1) el ESTADO ACTUAL del gasto en JSON y (2) el MENSAJE nuevo del usuario (puede venir de voz dictada).
Actualiza el gasto según el mensaje y devuelve el gasto COMPLETO + una `respuesta` breve y natural en español.

Reglas:
- `concepto`: descripción corta del gasto.
- `subtotal` (base) e `impuestos` por separado; si el usuario da solo un total, ponlo en `subtotal` e `impuestos` en 0, salvo que indique el IVA.
- Puedes fijar proveedor (nombre y NIT), número de factura, fecha y forma de pago.
- `tipo_gasto`: si el usuario dice la categoría (ej. "tipo de gasto arriendo", "es nómina"), ponla en `tipo_gasto`.
- `responsable`: si dice quién es el responsable (ej. "responsable Edward Valencia"), ponlo en `responsable`.
- Si un dato no se ha dicho, déjalo en "" o 0; NO inventes proveedores, NITs ni valores.
- La `respuesta` corta: confirma lo entendido y, si falta algo clave (concepto o valor), pídelo amablemente.
- Mantén lo que ya estaba salvo que el usuario lo cambie.
Devuelve solo el JSON del esquema (data = gasto + respuesta)."""


def gasto_vacio() -> dict:
    return {
        "proveedor": {"nombre_tirilla": "", "nit": ""},
        "documento": {"numero": "", "fecha": ""},
        "concepto": "", "forma_pago": "", "subtotal": 0, "impuestos": 0,
        "tipo_gasto": "", "responsable": "",
    }


def extraer_gasto(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Imagen de un recibo de gasto -> dict del gasto (GASTO_SCHEMA)."""
    return extraer_imagen(image_bytes, GASTO_SCHEMA, PROMPT_IMG, media_type)


def conversar_gasto(mensaje: str, gasto: Optional[dict] = None,
                    historial: Optional[list[dict]] = None) -> dict:
    """Un turno de chat para armar un gasto. Devuelve {"gasto": ..., "respuesta": ...}."""
    out = conversar_doc(
        mensaje, GASTO_SCHEMA, SYSTEM_CHAT,
        estado=gasto or gasto_vacio(), historial=historial, etiqueta_doc="GASTO",
    )
    return {"gasto": out.get("data") or gasto_vacio(), "respuesta": out.get("respuesta", "")}
