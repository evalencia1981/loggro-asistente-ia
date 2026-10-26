"""
loggro_intake.lista — Preset de captura de LISTAS de inventario (texto de WhatsApp o foto).

Los muchachos del bar mandan por WhatsApp cosas como:

    Conteo barra 28/09
    aguila 145
    poker: 60
    - 3 botellas de aguardiente antioqueño
    club dorada 2 canastas

Esto lo convierte en líneas {descripcion, cantidad, costo_unitario, producto_catalogo}.
Si se le pasa el catálogo de productos, Gemini propone para cada línea el nombre
EXACTO del producto del catálogo que corresponde ("pola" -> "Aguila Original"); el
backend lo traduce a _id. Sirve para ajustes, mermas, conteos e inventario inicial.
"""
from __future__ import annotations

from typing import Optional

from .gemini import generar_json
from .extractor import extraer_imagen

LISTA_SCHEMA = {
    "type": "object",
    "properties": {
        "fecha": {"type": "string"},
        "nota": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "descripcion": {"type": "string"},
                    "cantidad": {"type": "number"},
                    "costo_unitario": {"type": "number"},
                    "producto_catalogo": {"type": "string"},
                },
                "required": ["descripcion", "cantidad", "costo_unitario", "producto_catalogo"],
            },
        },
    },
    "required": ["fecha", "nota", "items"],
}

_REGLAS = """Reglas:
- Una línea por producto. `descripcion` = el producto tal como lo escribieron, en MAYÚSCULAS y sin la cantidad (ej. "AGUILA", "AGUARDIENTE ANTIOQUEÑO").
- `cantidad` = número de UNIDADES. Acepta "145", "x3", "3 und", "tres", "1/2", "0,5" (coma decimal colombiana). Si dicen canastas/cajas/pacas/six pack y NO dicen cuántas unidades trae cada una, deja la cantidad tal como la dijeron (ej. 2), NO la multipliques, y pon el empaque entre paréntesis en la `descripcion` (ej. "CLUB DORADA (CANASTA)") para que una persona lo revise.
- `costo_unitario` = costo por unidad solo si lo escriben (ej. "a 2.400", "$2400 c/u"). Si dan el total de la línea, divídelo por la cantidad. Si no hay costo, 0. En Colombia el punto es separador de miles: "2.400" = 2400.
- Si el mismo producto aparece dos veces, suma las cantidades en una sola línea.
- Ignora saludos, firmas, horas de WhatsApp ("[28/9 10:14 p. m.] Juan:"), emojis y líneas sin producto.
- `fecha`: la fecha del conteo si aparece, en formato YYYY-MM-DD; si no, "".
- `nota`: título o contexto corto si lo hay (ej. "Conteo barra"); si no, "".
- No inventes productos ni cantidades."""

_REGLA_CATALOGO = """- `producto_catalogo`: el nombre EXACTO (copiado letra por letra) del producto del CATÁLOGO que corresponde a la línea. Considera jerga y abreviaturas ("pola"/"aguilita" -> una Aguila; "guaro" -> aguardiente; "cocacola" -> Coca-Cola). Si hay varias presentaciones y la lista no dice cuál, elige la más común (la normal, no la light/mini). Si no hay un producto razonable en el catálogo, deja "" — NUNCA inventes un nombre que no esté en el catálogo."""

PROMPT_TEXTO = """Eres un asistente de inventario de un bar en Colombia. Te pego una lista de productos y cantidades que el personal mandó por WhatsApp (conteo, mermas, faltantes o inventario inicial).
Conviértela al esquema JSON indicado.
{reglas}
{regla_catalogo}
{catalogo}
LISTA:
{texto}"""

PROMPT_IMAGEN = """Eres un asistente de inventario de un bar en Colombia. La imagen es una lista de productos y cantidades (escrita a mano, en una planilla o un pantallazo de WhatsApp).
Conviértela al esquema JSON indicado.
{reglas}
{regla_catalogo}
{catalogo}"""


def _bloque_catalogo(catalogo: Optional[list[str]]) -> tuple[str, str]:
    if not catalogo:
        return "- `producto_catalogo`: deja \"\" en todas las líneas.", ""
    nombres = "\n".join(sorted({n.strip() for n in catalogo if n and n.strip()}))
    return _REGLA_CATALOGO, f"\nCATÁLOGO DE PRODUCTOS (un nombre por línea):\n{nombres}\n"


def extraer_lista_texto(texto: str, catalogo: Optional[list[str]] = None) -> dict:
    """Texto pegado (WhatsApp, notas) -> {fecha, nota, items[]} según LISTA_SCHEMA."""
    regla_cat, bloque = _bloque_catalogo(catalogo)
    prompt = PROMPT_TEXTO.format(reglas=_REGLAS, regla_catalogo=regla_cat,
                                 catalogo=bloque, texto=texto.strip())
    return generar_json([{"text": prompt}], LISTA_SCHEMA)


def extraer_lista_imagen(image_bytes: bytes, media_type: str = "image/jpeg",
                         catalogo: Optional[list[str]] = None) -> dict:
    """Foto de una lista (a mano, planilla, pantallazo) -> {fecha, nota, items[]}."""
    regla_cat, bloque = _bloque_catalogo(catalogo)
    prompt = PROMPT_IMAGEN.format(reglas=_REGLAS, regla_catalogo=regla_cat, catalogo=bloque)
    return extraer_imagen(image_bytes, LISTA_SCHEMA, prompt, media_type)
