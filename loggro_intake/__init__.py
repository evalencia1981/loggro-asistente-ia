"""
loggro_intake — Captura de facturas de compra (foto o chat) para Loggro.

Paquete reutilizable: extrae los datos de una factura/tirilla y los devuelve en un
JSON estructurado y estable (sección 4.1 del spec). Dos formas de entrada:

    from loggro_intake import extraer_tirilla        # desde imagen (visión)
    from loggro_intake import conversar              # desde lenguaje natural (chat)

Ambas devuelven el mismo esquema de factura (FACTURA_SCHEMA), listo para homologar
y registrar en Loggro. Usa Google Gemini (free tier) por debajo; requiere
GEMINI_API_KEY en el entorno. Modelo configurable con LOGGRO_EXTRACTOR_MODEL.

Diseñado para reutilizarse en otros proyectos: no depende de FastAPI ni del front.
"""
from .schema import FACTURA_SCHEMA, media_type_from_name
from .extractor import extraer_tirilla
from .chat import conversar, CHAT_SCHEMA

__all__ = [
    "FACTURA_SCHEMA",
    "CHAT_SCHEMA",
    "media_type_from_name",
    "extraer_tirilla",
    "conversar",
]
