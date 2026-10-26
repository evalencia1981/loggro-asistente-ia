"""
movimientos_inventario.py
Movimientos de inventario de Loggro distintos a la compra: ajustes, mermas,
devoluciones, "otro", entrada con costo, y el CONTEO FÍSICO (inventario inicial).

Lógica pura (sin FastAPI): recibe productos ya leídos de Loggro y arma payloads
para POST /inventories. Replica lo que hace la web de Loggro
(restobar.loggro.com -> js/controllers/inventoryController.js):
  * la cantidad va SIEMPRE positiva: el tipo (isSubtracted) decide si suma o resta;
  * el precio por defecto de cada línea es el `pricePurchase` del producto en la
    bodega; en la merma (10) es el `avgCost` (o pricePurchase si no hay);
  * en "Entrada con costo" (15) el costo unitario lo da el usuario;
  * los movimientos que no son compra van con `invoice: null` y sin proveedor.

CONFIRMADO contra Virus pub (2026-09-29): Entrada-Ajuste (3) y Salida-Ajuste (6)
con este payload mueven el stock ±cantidad, NO tocan el avgCost, Loggro calcula el
`total` solo, y DELETE /inventories/{_id} deja el stock como estaba.
"""
from __future__ import annotations

from typing import Any, Optional

# Tipos que se ofrecen en la app. Se excluyen a propósito:
#   1 Entrada-Compra (tiene su propia pestaña), 8 Traslados (una sola bodega),
#   9 Producción, 11 Inventario a cero (borra todo el stock), 12/13 Pedidos de consumo.
TIPOS: list[dict[str, Any]] = [
    {"id": 3, "nombre": "Entrada - Ajuste", "resta": False, "costo": "compra",
     "ayuda": "Aparecieron unidades de más (conteo por encima del sistema)."},
    {"id": 6, "nombre": "Salida - Ajuste", "resta": True, "costo": "compra",
     "ayuda": "Faltan unidades (conteo por debajo del sistema)."},
    {"id": 10, "nombre": "Salida - Merma", "resta": True, "costo": "promedio",
     "ayuda": "Producto dañado, vencido, roto o regalado."},
    {"id": 15, "nombre": "Entrada con costo", "resta": False, "costo": "usuario",
     "ayuda": "Entrada que SÍ recalcula el costo promedio (ej. inventario inicial con costos)."},
    {"id": 2, "nombre": "Entrada - Devolución", "resta": False, "costo": "compra",
     "ayuda": "Regresa a la bodega producto que había salido."},
    {"id": 5, "nombre": "Salida - Devolución", "resta": True, "costo": "compra",
     "ayuda": "Producto que se le devuelve al proveedor."},
    {"id": 4, "nombre": "Entrada - Otro", "resta": False, "costo": "compra", "ayuda": ""},
    {"id": 7, "nombre": "Salida - Otro", "resta": True, "costo": "compra", "ayuda": ""},
]
TIPOS_POR_ID = {t["id"]: t for t in TIPOS}

TIPO_AJUSTE_ENTRADA = 3
TIPO_AJUSTE_SALIDA = 6


def _id(ref: Any) -> Optional[str]:
    """Una referencia de Loggro puede venir como id o como objeto con _id."""
    if isinstance(ref, dict):
        return ref.get("_id")
    return ref


def stock_en_bodega(producto: dict, location_id: str) -> dict[str, float]:
    """{stock, avgCost, pricePurchase} del producto en la bodega indicada.

    El stock real vive en product.locationsStock[] (product.stock en la raíz es 0).
    """
    for ls in producto.get("locationsStock") or []:
        if _id(ls.get("locationStock")) == location_id:
            return {
                "stock": float(ls.get("stock") or 0),
                "avgCost": float(ls.get("avgCost") or 0),
                "pricePurchase": float(ls.get("pricePurchase") or 0),
            }
    return {"stock": 0.0, "avgCost": 0.0, "pricePurchase": 0.0}


def costo_por_defecto(tipo_id: int, producto: dict, location_id: str) -> float:
    """El mismo precio que pondría la web de Loggro al agregar la línea."""
    s = stock_en_bodega(producto, location_id)
    if TIPOS_POR_ID.get(tipo_id, {}).get("costo") == "promedio":
        return s["avgCost"] or s["pricePurchase"]
    return s["pricePurchase"]


def construir_payload(tipo_id: int, lineas: list[dict], location_id: str,
                      fecha_iso: str, nota: str = "") -> dict:
    """lineas = [{product_id, cantidad (>0), costo_unitario}] -> body de POST /inventories."""
    if tipo_id not in TIPOS_POR_ID:
        raise ValueError(f"Tipo de movimiento no soportado: {tipo_id}")
    if not lineas:
        raise ValueError("No hay líneas para registrar.")
    vistos: set[str] = set()
    ingredientes = []
    for ln in lineas:
        pid = ln["product_id"]
        if pid in vistos:
            # Loggro rechaza en su web el mismo producto dos veces en un movimiento.
            raise ValueError("Hay un producto repetido en la lista; sume las cantidades.")
        vistos.add(pid)
        cant = float(ln["cantidad"])
        if cant <= 0:
            raise ValueError("Todas las cantidades deben ser mayores a cero.")
        costo = float(ln.get("costo_unitario") or 0)
        if costo < 0:
            raise ValueError("El costo unitario no puede ser negativo.")
        ingredientes.append({
            "ingredient": pid,
            "quantity": cant,
            "price": round(costo, 2),
            "locationStock": location_id,
            "note": ln.get("nota") or "",
        })
    return {
        "date": f"{fecha_iso}T12:00:00.000Z",
        "type": tipo_id,
        "provider": None,
        "note": (nota or "").strip(),
        "invoice": None,
        "ingredients": ingredientes,
    }


def diferencias_conteo(contados: list[dict], productos: dict[str, dict],
                       location_id: str) -> list[dict]:
    """Compara lo contado con el stock actual de Loggro.

    contados = [{product_id, contado}]; productos = {_id: producto de Loggro}.
    Devuelve una fila por producto con stock_sistema, contado, diferencia y el costo
    que llevaría el ajuste. Los productos que NO están en la lista no se tocan.
    """
    filas = []
    for c in contados:
        prod = productos.get(c["product_id"])
        if prod is None:
            raise ValueError(f"Producto no encontrado en Loggro: {c['product_id']}")
        s = stock_en_bodega(prod, location_id)
        contado = float(c["contado"])
        if contado < 0:
            raise ValueError(f"El conteo de '{prod.get('name')}' no puede ser negativo.")
        dif = round(contado - s["stock"], 4)
        filas.append({
            "product_id": c["product_id"],
            "nombre": prod.get("name") or "",
            "stock_sistema": s["stock"],
            "contado": contado,
            "diferencia": dif,
            "costo_unitario": s["pricePurchase"],
        })
    return filas


def lineas_ajuste(filas: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separa las diferencias del conteo en (entradas, salidas) con cantidades positivas."""
    entradas, salidas = [], []
    for f in filas:
        if f["diferencia"] > 0:
            entradas.append({"product_id": f["product_id"], "cantidad": f["diferencia"],
                             "costo_unitario": f["costo_unitario"]})
        elif f["diferencia"] < 0:
            salidas.append({"product_id": f["product_id"], "cantidad": -f["diferencia"],
                            "costo_unitario": f["costo_unitario"]})
    return entradas, salidas
