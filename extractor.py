"""
extractor.py — Shim de compatibilidad.

La lógica real vive ahora en el paquete reutilizable `loggro_intake`. Este módulo
se conserva para no romper imports antiguos (`import extractor`).

Nuevo código: usa `from loggro_intake import extraer_tirilla, media_type_from_name`.
"""
from loggro_intake.extractor import extraer_tirilla, media_type_from_name  # noqa: F401
from loggro_intake.schema import FACTURA_SCHEMA as EXTRACCION_SCHEMA  # noqa: F401
