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
from .extractor import extraer_tirilla, extraer_imagen
from .chat import conversar, conversar_doc, CHAT_SCHEMA
from . import gasto
from .gasto import GASTO_SCHEMA, extraer_gasto, conversar_gasto

__all__ = [
    "FACTURA_SCHEMA",
    "GASTO_SCHEMA",
    "CHAT_SCHEMA",
    "media_type_from_name",
    "extraer_imagen",
    "extraer_tirilla",
    "conversar",
    "conversar_doc",
    "gasto",
    "extraer_gasto",
    "conversar_gasto",
]
