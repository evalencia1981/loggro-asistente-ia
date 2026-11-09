"""
informe_precios.py
Precio de venta, costo y margen de cada producto de la carta.

De dónde sale cada número (bodega principal, `locationsStock`):
  * Precio  -> `locationsStock[].price` (el `price` de la raíz viene en 0).
  * Costo, según cómo controla inventario el producto:
      - Por unidad / mixto -> `avgCost` (costo promedio); si está en 0, el
        `pricePurchase` (último precio de compra).
      - Con receta         -> suma de cantidad x costo unitario de cada
        ingrediente, con los costos frescos de GET /ingredients.
      - Combo              -> no se calcula: depende de lo que elija el cliente.
      - Sin inventario     -> Loggro no guarda costo.

Uso:
    python -X utf8 informe_precios.py            # consola + CSV
    python -X utf8 informe_precios.py --html     # + informe_precios.html
    python -X utf8 informe_precios.py --inactivos  # incluye productos inactivos

Siempre escribe `informe_precios.csv` junto al script.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import statistics
from pathlib import Path

from informe_utilidad import pesos
from loggro_client import LoggroClient

RAIZ = Path(__file__).parent
CSV_SALIDA = RAIZ / "informe_precios.csv"
HTML_SALIDA = RAIZ / "informe_precios.html"

# Margen por debajo del cual un producto se marca para revisar.
MARGEN_BAJO = 30.0
# Un costo por debajo de esta fracción del precio casi siempre es un dato mal
# cargado (aparecen costos de $1 y $5 en cervezas de $17.000).
COSTO_MINIMO = 0.03

# Notas que vuelven un producto "para revisar"; las de ERROR son datos mal
# cargados en Loggro (el margen que sale de ahí no sirve).
ERROR = ("costo mayor", "sospechosamente")
REVISAR = ERROR + ("margen bajo", "sin precio", "sin costo cargado", "ingredientes sin costo")


def _id(ref) -> str | None:
    return ref.get("_id") if isinstance(ref, dict) else ref


def _bodega(item: dict) -> dict:
    """locationsStock viene como lista o, en /ingredients, a veces como objeto suelto."""
    ls = item.get("locationsStock") or []
    if isinstance(ls, dict):
        return ls
    return ls[0] if ls else {}


def costo_unitario(item: dict) -> tuple[float, str]:
    b = _bodega(item)
    avg = float(b.get("avgCost") or 0)
    if avg > 0:
        return avg, "promedio"
    compra = float(b.get("pricePurchase") or 0)
    if compra > 0:
        return compra, "última compra"
    return 0.0, ""


def costo_receta(prod: dict, por_id: dict[str, dict]) -> tuple[float, str, list[str]]:
    """Costo de un producto con receta. Devuelve (costo, fuente, ingredientes sin costo)."""
    total, faltan = 0.0, []
    for linea in prod.get("ingredients") or []:
        ing = linea.get("ingredient") or {}
        fresco = por_id.get(_id(ing)) or ing
        c, _ = costo_unitario(fresco)
        if c <= 0:
            faltan.append(fresco.get("name") or "?")
        total += c * float(linea.get("quantity") or 0)
    return total, "receta", faltan


def calcular(productos: list[dict], ingredientes: list[dict], incluir_inactivos: bool) -> list[dict]:
    por_id = {i["_id"]: i for i in ingredientes}
    filas = []
    for p in productos:
        if not p.get("isActive") and not incluir_inactivos:
            continue
        b = _bodega(p)
        precio = float(b.get("price") or p.get("price") or 0)
        tipo_inv = p.get("inventoryType")
        notas: list[str] = []

        if p.get("type") == "Combo":
            costo, fuente = None, "combo"
        elif p.get("ingredients"):
            costo, fuente, faltan = costo_receta(p, por_id)
            if faltan:
                notas.append("ingredientes sin costo: " + ", ".join(faltan))
        elif tipo_inv in ("PerUnit", "Mixed"):
            costo, fuente = costo_unitario(p)
        else:
            costo, fuente = None, "sin inventario"

        if costo is not None and costo <= 0:
            costo, fuente = None, "sin costo"
            notas.append("sin costo cargado")

        margen = utilidad = None
        if costo is not None and precio > 0:
            utilidad = precio - costo
            margen = utilidad / precio * 100
            if costo > precio:
                notas.append("costo mayor que el precio")
            elif costo < precio * COSTO_MINIMO:
                notas.append("costo sospechosamente bajo")
            elif margen < MARGEN_BAJO:
                notas.append(f"margen bajo (<{MARGEN_BAJO:.0f}%)")
        if fuente == "combo":
            notas.append("combo: costo según lo que se elija")
        elif fuente == "sin inventario":
            notas.append("no controla inventario")
        if precio <= 0:
            notas.append("sin precio de venta")

        texto = "; ".join(notas)
        if any(n in texto for n in ERROR):
            estado = "error"
        elif any(n in texto for n in REVISAR):
            estado = "revisar"
        else:
            estado = "ok"

        cat = p.get("category")
        filas.append({
            "id": p.get("_id"),
            "estado": estado,
            "categoria": (cat.get("name") if isinstance(cat, dict) else "") or "Sin categoría",
            "producto": (p.get("name") or "").strip(),
            "activo": bool(p.get("isActive")),
            "precio": precio,
            "costo": costo,
            "fuente_costo": fuente,
            "utilidad": utilidad,
            "margen": margen,
            "notas": "; ".join(notas),
        })
    filas.sort(key=lambda f: (f["categoria"].lower(), f["producto"].lower()))
    return filas


def resumen(filas: list[dict]) -> dict:
    con = [f for f in filas if f["margen"] is not None]
    return {
        "productos": len(filas),
        "con_costo": len(con),
        "sin_costo": len(filas) - len(con),
        # Mediana: los costos mal cargados (márgenes de -500%) arrastran el promedio.
        "margen_mediano": statistics.median(f["margen"] for f in con) if con else 0,
        "revisar": sum(1 for f in filas if f["estado"] != "ok"),
        "errores": sum(1 for f in filas if f["estado"] == "error"),
    }


def _p(v: float | None) -> str:
    return "—" if v is None else pesos(v)


def _m(v: float | None) -> str:
    return "—" if v is None else f"{v:.0f}%"


def imprimir(filas: list[dict], r: dict) -> None:
    cat = None
    for f in filas:
        if f["categoria"] != cat:
            cat = f["categoria"]
            print(f"\n== {cat} ==")
        print(f"  {f['producto'][:38]:<38} {_p(f['precio']):>11} {_p(f['costo']):>11} "
              f"{_m(f['margen']):>5}  {f['notas']}")
    print(f"\n{r['productos']} productos · {r['con_costo']} con costo · "
          f"margen típico (mediana) {r['margen_mediano']:.0f}% · {r['revisar']} para revisar")


def escribir_csv(filas: list[dict], ruta: Path) -> None:
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Categoría", "Producto", "Activo", "Precio", "Costo", "Fuente costo",
                    "Utilidad", "Margen %", "Notas"])
        for f in filas:
            w.writerow([f["categoria"], f["producto"], "Sí" if f["activo"] else "No",
                        round(f["precio"]),
                        "" if f["costo"] is None else round(f["costo"]),
                        f["fuente_costo"],
                        "" if f["utilidad"] is None else round(f["utilidad"]),
                        "" if f["margen"] is None else round(f["margen"], 1),
                        f["notas"]])
    print(f"  CSV  -> {ruta}")


def escribir_html(filas: list[dict], r: dict, ruta: Path) -> None:
    e = html.escape
    cuerpo, cat = [], None
    for f in filas:
        if f["categoria"] != cat:
            cat = f["categoria"]
            cuerpo.append(f"<tr class=cat><td colspan=6>{e(cat)}</td></tr>")
        cls = "neg" if f["margen"] is not None and f["margen"] < 0 else (
            "warn" if f["margen"] is not None and f["margen"] < MARGEN_BAJO else "")
        cuerpo.append(
            f"<tr><td>{e(f['producto'])}</td><td class=n>{_p(f['precio'])}</td>"
            f"<td class=n>{_p(f['costo'])}<small>{e(f['fuente_costo'])}</small></td>"
            f"<td class=n>{_p(f['utilidad'])}</td><td class='n {cls}'>{_m(f['margen'])}</td>"
            f"<td class=nt>{e(f['notas'])}</td></tr>")
    hoy = dt.date.today().isoformat()
    ruta.write_text(f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Precios y costos</title>
<style>
 body{{font:14px/1.45 system-ui,sans-serif;margin:2rem auto;max-width:1000px;padding:0 16px;color:#1a1a1a;background:#fff}}
 h1{{font-size:1.4rem;margin-bottom:.2rem}} .sub{{color:#666;font-size:.85rem;margin-bottom:1.2rem}}
 .kpi{{display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1.2rem}} .kpi b{{display:block;font-size:1.3rem}}
 .kpi div{{color:#666;font-size:.8rem}}
 .wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%}}
 th,td{{padding:.4rem .5rem;border-bottom:1px solid #eee;vertical-align:top}}
 th{{text-align:left;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#666}}
 .n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
 .n small{{display:block;color:#999;font-size:.7rem}}
 .cat td{{background:#f5f5f5;font-weight:700;padding-top:.7rem}}
 .neg{{color:#c2415a;font-weight:700}} .warn{{color:#b7791f}} .nt{{color:#8a5a00;font-size:.8rem}}
</style>
<h1>Precios y costos por producto</h1>
<div class=sub>Virus pub · {hoy} · costo = promedio de Loggro, o último precio de compra si el promedio está en 0; recetas = suma de ingredientes.</div>
<div class=kpi>
 <div><b>{r['productos']}</b>productos</div><div><b>{r['con_costo']}</b>con costo</div>
 <div><b>{r['margen_mediano']:.0f}%</b>margen típico (mediana)</div><div><b>{r['revisar']}</b>para revisar</div>
</div>
<div class=wrap><table>
<thead><tr><th>Producto</th><th class=n>Precio</th><th class=n>Costo</th>
<th class=n>Utilidad</th><th class=n>Margen</th><th>Notas</th></tr></thead>
<tbody>{''.join(cuerpo)}</tbody></table></div>
""", encoding="utf-8")
    print(f"  HTML -> {ruta}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--inactivos", action="store_true", help="incluir productos inactivos")
    a = ap.parse_args()

    cli = LoggroClient()
    cli.login()
    filas = calcular(cli.get_products(), cli.get_inventory_items(), a.inactivos)
    r = resumen(filas)
    imprimir(filas, r)
    escribir_csv(filas, CSV_SALIDA)
    if a.html:
        escribir_html(filas, r, HTML_SALIDA)


if __name__ == "__main__":
    main()
