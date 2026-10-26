"""
informe_stock.py
Existencias para hacer pedidos: por producto o ingrediente, el stock al inicio del
periodo, lo que entró, lo que se consumió, el stock actual y cuánto pedir.

Fuentes (todas de Loggro, solo lectura):
  * GET /ingredients            -> qué lleva inventario, stock actual, mínimo, costo.
  * kardex (log-inventories)    -> cada venta/pedido/compra/ajuste con el stock que
                                   dejó; de ahí salen el inicial y el consumo.
  * GET /inventories?type=1     -> la última compra de cada ítem: a quién pedírselo.

El periodo siempre termina AHORA ("últimos N días"): así el stock final es el del
catálogo, que es la cifra que el dueño ve en Loggro, y el inicial se reconstruye
hacia atrás con el kardex.

Lo que se sugiere pedir:
    objetivo = max(mínimo de Loggro, consumo diario × días de cobertura)
    pedir    = objetivo - stock actual   (un stock negativo cuenta como 0)

Uso:
    python -X utf8 informe_stock.py                  # últimos 15 días, cobertura 7
    python -X utf8 informe_stock.py --dias 30 --cobertura 10 --solo-pedir
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
from collections import defaultdict
from pathlib import Path

from loggro_client import LoggroClient, LOCATION_STOCK_ID
from informe_utilidad import TZ_BOGOTA, CORTE_JORNADA

CSV_SALIDA = Path(__file__).with_name("informe_stock.csv")

# Tipos del kardex. Lo que es consumo (sale por la venta o se regala) cuenta para
# la sugerencia de pedido; las compras son entradas; el resto son ajustes.
CONSUMO = {"FACTURACION", "PEDIDO_INTERNO", "PEDIDO_CORTESIA"}
COMPRA = {"ENTRADA_COMPRA"}


def _id(ref) -> str | None:
    return ref.get("_id") if isinstance(ref, dict) else ref


def _bodega(item: dict, location_id: str) -> dict:
    """locationsStock viene como lista o, en /ingredients, a veces como objeto suelto."""
    ls = item.get("locationsStock") or []
    if isinstance(ls, dict):
        ls = [ls]
    for b in ls:
        if _id(b.get("locationStock")) == location_id:
            return b
    return ls[0] if ls else {}


def delta_de_log(log: dict) -> float:
    """Cuánto movió el stock un log, cuando no hay un log anterior con qué comparar.

    El signo de `quantity` no es uniforme (verificado con 1.735 logs de oct-2026):
      * ventas y pedidos restan |quantity| (la cortesía a veces viene negativa);
      * entradas suman quantity;
      * INVENTARIO_A_CERO trae la cantidad negativa del stock que lleva a cero.
    Tipos que aún no se han visto (mermas, traslados…) caen en "resta".
    """
    q = float(log.get("quantity") or 0)
    tipo = log.get("type") or ""
    if tipo.startswith("ENTRADA"):
        return q
    if tipo == "INVENTARIO_A_CERO":
        return -q
    return -abs(q)


def ventana(dias: int, ahora: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    """Inicio y fin (UTC) de los últimos `dias` días, cortando en la jornada.

    El inicio es la hora de corte (6am Bogotá) de hace `dias` días: una noche de
    viernes no se parte por la mitad.
    """
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    local = ahora.astimezone(TZ_BOGOTA)
    hoy_jornada = (local - dt.timedelta(hours=CORTE_JORNADA)).date()
    inicio_local = dt.datetime.combine(hoy_jornada - dt.timedelta(days=dias - 1),
                                       dt.time(CORTE_JORNADA), tzinfo=TZ_BOGOTA)
    return inicio_local.astimezone(dt.timezone.utc), ahora


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ultimas_compras(compras: list[dict]) -> dict[str, dict]:
    """{ingrediente_id: {proveedor, fecha, cantidad}} de la compra más reciente.

    Se ordena por `createdOn` (cuándo se registró) y no por `date`: hay compras
    fechadas en 2030 por un dedazo que si no quedarían siempre como "la última".
    """
    salida: dict[str, dict] = {}
    for mov in sorted(compras, key=lambda m: m.get("createdOn") or ""):
        if mov.get("deleted"):
            continue
        prov = mov.get("provider") or {}
        nombre = (prov.get("tradename") or prov.get("name") or "").strip() if isinstance(prov, dict) else ""
        for ln in mov.get("ingredients") or []:
            iid = _id(ln.get("ingredient"))
            if iid:
                salida[iid] = {
                    "proveedor": nombre or "Sin proveedor",
                    "fecha": (mov.get("createdOn") or "")[:10],
                    "cantidad": float(ln.get("quantity") or 0),
                }
    return salida


def traer(cli: LoggroClient, dias: int) -> dict:
    """Lecturas crudas de Loggro para los últimos `dias` días."""
    ini, fin = ventana(dias)
    return {
        "items": cli.get_inventory_items(),
        "logs": cli.get_inventory_logs(_iso(ini), _iso(fin)),
        "compras": cli.get_movements(inventory_type_id=1),
        "desde": ini,
        "hasta": fin,
    }


def calcular(crudos: dict, dias: int, cobertura: int,
             location_id: str = LOCATION_STOCK_ID) -> dict:
    """Una fila por ítem con inicial, entradas, consumo, actual y sugerido a pedir."""
    logs_por_item: dict[str, list[dict]] = defaultdict(list)
    for log in crudos["logs"]:
        if _id(log.get("locationStock")) in (None, location_id) and log.get("ingredient"):
            logs_por_item[log["ingredient"]].append(log)
    compras = ultimas_compras(crudos["compras"])

    filas = []
    for it in crudos["items"]:
        if it.get("deleted") or not it.get("isActive", True):
            continue
        b = _bodega(it, location_id)
        actual = float(b.get("stock") or 0)
        minimo = float(b.get("stockMinimum") or 0)
        costo = float(b.get("avgCost") or 0) or float(b.get("pricePurchase") or 0)

        compras_p = consumo = ajustes = 0.0
        logs = sorted(logs_por_item.get(it["_id"], []),
                      key=lambda x: (x.get("createdOn") or "", x.get("_id") or ""))
        anterior = None
        for log in logs:
            cur = float(log.get("currentStock") or 0)
            # Entre dos logs seguidos la diferencia de currentStock es exacta; solo el
            # primero del periodo depende de la regla de signos.
            d = cur - anterior if anterior is not None else delta_de_log(log)
            anterior = cur
            tipo = log.get("type") or ""
            if tipo in CONSUMO:
                consumo -= d
            elif tipo in COMPRA:
                compras_p += d
            else:
                ajustes += d
        inicial = actual - (compras_p - consumo + ajustes)

        diario = consumo / dias if dias else 0.0
        objetivo = max(minimo, diario * cobertura)
        pedir = max(0.0, math.ceil(objetivo - max(actual, 0.0)))
        if actual <= 0 and not consumo and not minimo:
            estado = "sin_movimiento"  # en 0, sin ventas ni mínimo: no se está manejando
        elif actual <= 0:
            estado = "agotado"
        elif minimo and actual < minimo:
            estado = "bajo"
        elif diario and actual / diario < cobertura:
            estado = "alcanza_poco"
        else:
            estado = "ok"

        unidad = it.get("unit")
        ult = compras.get(it["_id"]) or {}
        categoria = it.get("category")
        filas.append({
            "id": it["_id"],
            "nombre": (it.get("name") or "").strip(),
            "categoria": (categoria.get("name") if isinstance(categoria, dict) else None) or (
                "Ingredientes" if it.get("isIngredient") else "Sin categoría"),
            "es_ingrediente": bool(it.get("isIngredient")),
            "unidad": (unidad.get("name") if isinstance(unidad, dict) else None) or "und",
            "inicial": round(inicial, 2),
            "compras": round(compras_p, 2),
            "consumo": round(consumo, 2),
            "ajustes": round(ajustes, 2),
            "actual": round(actual, 2),
            "minimo": minimo,
            "consumo_diario": round(diario, 2),
            "dias_alcanza": round(actual / diario, 1) if diario and actual > 0 else None,
            "pedir": pedir,
            "costo_unitario": round(costo),
            "costo_pedido": round(pedir * costo),
            "estado": estado,
            "proveedor": ult.get("proveedor") or "Sin compras registradas",
            "ultima_compra": ult.get("fecha"),
            "movimientos": len(logs),
        })

    filas.sort(key=lambda f: (f["proveedor"], f["categoria"], f["nombre"].lower()))
    return {
        "desde": _iso(crudos["desde"]),
        "hasta": _iso(crudos["hasta"]),
        "dias": dias,
        "cobertura": cobertura,
        "resumen": {
            "items": len(filas),
            "agotados": sum(f["estado"] == "agotado" for f in filas),
            "bajos": sum(f["estado"] in ("bajo", "alcanza_poco") for f in filas),
            "negativos": sum(f["actual"] < 0 for f in filas),
            "por_pedir": sum(f["pedir"] > 0 for f in filas),
            "costo_pedido": sum(f["costo_pedido"] for f in filas),
        },
        "filas": filas,
    }


# --------------------------------------------------------------------------- #
# Consola / CSV
# --------------------------------------------------------------------------- #
def escribir_csv(inf: dict, ruta: Path, solo_pedir: bool = False) -> None:
    cols = ["proveedor", "categoria", "nombre", "unidad", "inicial", "compras", "consumo",
            "ajustes", "actual", "minimo", "consumo_diario", "dias_alcanza", "pedir",
            "costo_unitario", "costo_pedido", "estado", "ultima_compra"]
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for fila in inf["filas"]:
            if not solo_pedir or fila["pedir"] > 0:
                w.writerow(fila)
    print(f"  CSV -> {ruta}")


def imprimir(inf: dict, solo_pedir: bool = False) -> None:
    r = inf["resumen"]
    print(f"\n  Existencias — últimos {inf['dias']} días, cobertura {inf['cobertura']} días")
    print(f"  {r['items']} ítems · {r['agotados']} agotados · {r['bajos']} bajos · "
          f"{r['negativos']} con stock negativo · {r['por_pedir']} por pedir\n")
    prov = None
    for f in inf["filas"]:
        if solo_pedir and f["pedir"] <= 0:
            continue
        if f["proveedor"] != prov:
            prov = f["proveedor"]
            print(f"  ── {prov}")
        print(f"     {f['nombre'][:30]:30} ini {f['inicial']:>7g}  +{f['compras']:<6g} "
              f"-{f['consumo']:<6g} aj {f['ajustes']:<+6g} = {f['actual']:>7g} {f['unidad']:<5} "
              f"mín {f['minimo']:<4g} pedir {f['pedir']:g}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Existencias y sugerido de pedido desde Loggro.")
    ap.add_argument("--dias", type=int, default=15, help="Días hacia atrás para medir el consumo.")
    ap.add_argument("--cobertura", type=int, default=7, help="Días que debe alcanzar el pedido.")
    ap.add_argument("--solo-pedir", action="store_true", help="Solo lo que hay que pedir.")
    args = ap.parse_args()

    cli = LoggroClient()
    cli.login()
    print(f"  Consultando Loggro (últimos {args.dias} días)…")
    inf = calcular(traer(cli, args.dias), args.dias, args.cobertura)
    imprimir(inf, args.solo_pedir)
    escribir_csv(inf, CSV_SALIDA, args.solo_pedir)


if __name__ == "__main__":
    main()
