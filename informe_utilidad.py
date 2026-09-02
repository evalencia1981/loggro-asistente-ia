"""
informe_utilidad.py
Informe de utilidad: ventas contra salidas (compras + gastos), mes a mes.

La utilidad aquí es de CAJA, no contable: se restan las compras del periodo, no
el costo de lo vendido. Se hace así a propósito —el costo por producto en Loggro
está cargado en menos de la mitad de la venta (Soda y Águila Light están en 0),
así que un margen calculado con `costProduct` mentiría. Las compras sí están
completas, y para un bar "cuánto entró contra cuánto salió" es la pregunta real.

Fuentes:
  * Ventas  -> GET /invoices sin filtro de status (todas las facturas vivas).
  * Compras -> GET /inventories, SOLO los movimientos "Entrada - Compra".
  * Gastos  -> GET /expenses.

Uso:
    python -X utf8 informe_utilidad.py                      # 6 meses hacia atrás
    python -X utf8 informe_utilidad.py --desde 2026-01-01
    python -X utf8 informe_utilidad.py --meses 12
    python -X utf8 informe_utilidad.py --html               # + informe_utilidad.html

Siempre escribe `informe_utilidad.csv` junto al script.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import statistics
from collections import defaultdict
from pathlib import Path

from loggro_client import LoggroClient

RAIZ = Path(__file__).parent
CSV_SALIDA = RAIZ / "informe_utilidad.csv"
HTML_SALIDA = RAIZ / "informe_utilidad.html"

# Colombia no tiene horario de verano: el offset es fijo.
TZ_BOGOTA = dt.timezone(dt.timedelta(hours=-5))

# Hora local en que empieza una jornada nueva. Un bar cierra de madrugada: lo
# vendido a la 1am del sábado es todavía la noche del viernes. Sin este corte,
# el 54% de las facturas (las que tienen hora UTC < 05:00) se cuentan un día
# después del que realmente fueron.
CORTE_JORNADA = 6

# Único tipo de movimiento de inventario que es plata saliendo. Los otros
# ("Entrada - Ajuste", "Inventario a cero", mermas...) son correcciones de
# stock: sumarlos como salida infla la pérdida.
TIPO_COMPRA = "Entrada - Compra"

# Una fecha fuera de esta ventana es un dedazo al teclear el año, no un dato.
# Ya aparecieron compras fechadas en 2030 que quedan fuera de todo informe.
ANIO_MIN, ANIO_MAX = 2020, dt.date.today().year + 1


def pesos(v: float) -> str:
    """35000 -> '$35.000' (formato colombiano)."""
    signo = "-" if v < 0 else ""
    return f"{signo}$" + f"{abs(round(v)):,}".replace(",", ".")


# --------------------------------------------------------------------------- #
# Fechas
# --------------------------------------------------------------------------- #
def jornada_de_venta(created_on: str) -> dt.date | None:
    """Jornada a la que pertenece una factura, desde su `createdOn` en UTC.

    Se convierte a hora de Bogotá y se resta el corte: así una venta de las 2am
    del sábado cuenta para el viernes, que es como se piensa la noche.
    """
    try:
        t = dt.datetime.fromisoformat((created_on or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    local = t.astimezone(TZ_BOGOTA)
    return (local - dt.timedelta(hours=CORTE_JORNADA)).date()


def fecha_de_registro(iso: str) -> dt.date | None:
    """Fecha de un gasto o una compra.

    OJO: aquí NO se convierte la zona horaria. Gastos y compras no guardan un
    instante sino un día, serializado como medianoche UTC ("2026-08-31T00:00:00.000Z").
    Pasarlo a Bogotá lo correría a las 7pm del día anterior y movería cada gasto
    una fecha hacia atrás. Se toma la parte de fecha tal cual.
    """
    try:
        return dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None


def fecha_plausible(f: dt.date | None) -> bool:
    return bool(f) and ANIO_MIN <= f.year <= ANIO_MAX


# --------------------------------------------------------------------------- #
# Traída de datos
# --------------------------------------------------------------------------- #
def _paginar_invoices(cli: LoggroClient, di: str, de: str, limit: int = 100) -> list[dict]:
    """GET /invoices paginado. Sin `status` trae todas las ventas, no solo crédito."""
    todas: list[dict] = []
    page = 0
    while True:
        r = cli.s.get(f"{cli.base_url}/invoices", timeout=cli.timeout, params={
            "dateInit": di, "dateEnd": de, "pagination": "true", "limit": limit, "page": page,
        })
        if r.status_code == 401:
            cli.login()
            continue
        r.raise_for_status()
        d = r.json()
        filas = d.get("data", []) if isinstance(d, dict) else d
        todas.extend(filas)
        total = d.get("count", len(todas)) if isinstance(d, dict) else len(todas)
        page += 1
        if not filas or len(todas) >= total:
            return todas


def traer(cli: LoggroClient, desde: dt.date, hasta: dt.date) -> dict[str, list[dict]]:
    """Ventas, compras y gastos del rango. Devuelve las listas crudas.

    Se pide un margen de un día a cada lado: por el corte de jornada, una venta
    de la madrugada del día siguiente todavía pertenece al último día del rango.
    """
    di = f"{desde - dt.timedelta(days=1)}T00:00:00.000Z"
    de = f"{hasta + dt.timedelta(days=2)}T00:00:00.000Z"

    ventas = _paginar_invoices(cli, di, de)

    r = cli.s.get(f"{cli.base_url}/inventories", timeout=cli.timeout, params={
        "dateInit": di, "dateEnd": de, "pagination": "true", "limit": 1000, "page": 0,
    })
    r.raise_for_status()
    d = r.json()
    movimientos = d.get("data", d) if isinstance(d, dict) else d

    gastos = cli.get_expenses(di, de)
    return {"ventas": ventas, "movimientos": movimientos, "gastos": gastos}


# --------------------------------------------------------------------------- #
# Agrupación (la comparte el endpoint /api/utilidad, para que web y consola
# no puedan dar cifras distintas)
# --------------------------------------------------------------------------- #
def total_gasto(g: dict) -> float:
    return (g.get("subTotal") or 0) + (g.get("taxes") or 0)


def agrupar(crudos: dict[str, list[dict]], desde: dt.date, hasta: dt.date) -> dict:
    """Arma el informe: filas por mes, totales y alertas de datos faltantes.

    El filtrado por fecha se hace AQUÍ y no se confía en el de la API:
    /inventories devuelve movimientos fuera del rango cuando la ventana es
    amplia (pidiendo desde marzo llegaron compras de febrero).
    """
    meses: dict[str, dict] = defaultdict(
        lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0,
                 "n_facturas": 0, "n_compras": 0, "n_gastos": 0}
    )
    dias: dict[dt.date, dict] = defaultdict(lambda: {"ventas": 0.0, "salidas": 0.0})
    descartadas: list[dict] = []

    for f in crudos["ventas"]:
        if (f.get("deletedInfo") or {}).get("isDeleted"):
            continue
        d = jornada_de_venta(f.get("createdOn"))
        if not d or not (desde <= d <= hasta):
            continue
        monto = f.get("total") or 0          # no incluye propina: no es ingreso del negocio
        meses[d.strftime("%Y-%m")]["ventas"] += monto
        meses[d.strftime("%Y-%m")]["n_facturas"] += 1
        dias[d]["ventas"] += monto

    for m in crudos["movimientos"]:
        if m.get("deleted") or m.get("typeName") != TIPO_COMPRA:
            continue
        d = fecha_de_registro(m.get("date"))
        monto = m.get("total") or 0
        if not fecha_plausible(d):
            descartadas.append({"tipo": "compra", "fecha": (m.get("date") or "")[:10],
                                "monto": monto, "concepto": (m.get("provider") or {}).get("name", "—"),
                                "registrado": (m.get("createdOn") or "")[:10]})
            continue
        if not (desde <= d <= hasta):
            continue
        meses[d.strftime("%Y-%m")]["compras"] += monto
        meses[d.strftime("%Y-%m")]["n_compras"] += 1
        dias[d]["salidas"] += monto

    for g in crudos["gastos"]:
        if g.get("deleted"):
            continue
        d = fecha_de_registro(g.get("date"))
        monto = total_gasto(g)
        if not fecha_plausible(d):
            descartadas.append({"tipo": "gasto", "fecha": (g.get("date") or "")[:10],
                                "monto": monto, "concepto": g.get("description") or "—",
                                "registrado": (g.get("createdOn") or "")[:10]})
            continue
        if not (desde <= d <= hasta):
            continue
        meses[d.strftime("%Y-%m")]["gastos"] += monto
        meses[d.strftime("%Y-%m")]["n_gastos"] += 1
        dias[d]["salidas"] += monto

    filas = []
    for periodo in sorted(meses):
        v = meses[periodo]
        salidas = v["compras"] + v["gastos"]
        filas.append({
            "periodo": periodo,
            **v,
            "salidas": salidas,
            "utilidad": v["ventas"] - salidas,
            "margen": (v["ventas"] - salidas) / v["ventas"] * 100 if v["ventas"] else 0.0,
            "peso_salidas": salidas / v["ventas"] * 100 if v["ventas"] else 0.0,
        })

    tv = sum(f["ventas"] for f in filas)
    tc = sum(f["compras"] for f in filas)
    tg = sum(f["gastos"] for f in filas)
    total = {
        "ventas": tv, "compras": tc, "gastos": tg, "salidas": tc + tg,
        "utilidad": tv - tc - tg,
        "margen": (tv - tc - tg) / tv * 100 if tv else 0.0,
        "n_facturas": sum(f["n_facturas"] for f in filas),
        "n_compras": sum(f["n_compras"] for f in filas),
        "n_gastos": sum(f["n_gastos"] for f in filas),
    }

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "corte_jornada": CORTE_JORNADA,
        "periodos": filas,
        "total": total,
        "alertas": detectar_faltantes(filas, dias, descartadas),
    }


# --------------------------------------------------------------------------- #
# ¿Faltan gastos por registrar?
# --------------------------------------------------------------------------- #
# Cuánto puede bajar el peso de las salidas sobre la venta, respecto a la
# mediana de los demás meses, antes de sospechar que faltan registros. Un mes
# con margen mucho mejor que el resto casi nunca es un mes bueno: es un mes al
# que le faltan facturas por meter.
#
# 0.85 = se avisa cuando las salidas pesan 15% menos que en los demás meses.
# Con 0.75 no saltaba agosto (68% contra una mediana de 83%), que es justo el
# caso que hay que mirar. Es un aviso para ir a revisar, no un veredicto.
DESVIACION_SOSPECHOSA = 0.85


def detectar_faltantes(filas: list[dict], dias: dict[dt.date, dict],
                       descartadas: list[dict]) -> list[dict]:
    """Señales de que la información está incompleta. Son avisos, no veredictos.

    Ninguna prueba que "falta" un gasto: prueban que un mes se comporta distinto
    a los demás, que es donde hay que ir a mirar.
    """
    alertas: list[dict] = []

    # 1. Fechas imposibles: quedan fuera de todo informe, en el mes que sea.
    if descartadas:
        alertas.append({
            "tipo": "fecha_imposible",
            "severidad": "alta",
            "titulo": f"{len(descartadas)} registros con fecha imposible",
            "detalle": (f"Suman {pesos(sum(d['monto'] for d in descartadas))} y no entran en "
                        "ningún mes. Casi siempre es un dedazo en el año al digitar."),
            "items": sorted(descartadas, key=lambda d: -d["monto"]),
        })

    # 2. Meses donde las salidas pesan mucho menos que de costumbre.
    cons = [f for f in filas if f["ventas"] > 0]
    if len(cons) >= 3:
        for f in cons:
            otros = [o["peso_salidas"] for o in cons if o["periodo"] != f["periodo"]]
            mediana = statistics.median(otros)
            if mediana and f["peso_salidas"] < mediana * DESVIACION_SOSPECHOSA:
                falta = (mediana - f["peso_salidas"]) / 100 * f["ventas"]
                alertas.append({
                    "tipo": "salidas_bajas",
                    "severidad": "alta",
                    "titulo": f"{f['periodo']}: las salidas pesan {f['peso_salidas']:.0f}% de la venta",
                    "detalle": (f"En los demás meses pesan {mediana:.0f}%. Si este mes fuera normal, "
                                f"faltarían del orden de {pesos(falta)} en compras o gastos."),
                    "periodo": f["periodo"],
                })

    # 3. Días con venta pero sin una sola salida registrada.
    sin_salidas = sorted(d for d, v in dias.items() if v["ventas"] > 0 and v["salidas"] == 0)
    if sin_salidas:
        alertas.append({
            "tipo": "dias_sin_salidas",
            "severidad": "media",
            "titulo": f"{len(sin_salidas)} días con ventas y ningún gasto ni compra",
            "detalle": ("Se vendió pero no se registró nada de salida. Puede ser real "
                        "(no se compró nada ese día) o puede ser que falte digitarlo."),
            "items": [d.isoformat() for d in sin_salidas],
        })

    # 4. Beneficiarios recurrentes sin pago hace más de un periodo.
    #    Reutiliza la lista de nómina; si no hay almacén, se omite en silencio.
    try:
        import recurrentes_store

        hoy = dt.date.today()
        vencidos = []
        for r in recurrentes_store.listar():
            periodo = recurrentes_store.DIAS_PERIODO.get(r.get("periodicidad") or "")
            if not periodo or not r.get("ultimo_pago"):
                continue
            dias_pasados = (hoy - dt.date.fromisoformat(r["ultimo_pago"])).days
            if dias_pasados >= periodo * 2:
                vencidos.append({"nombre": r["nombre"], "dias": dias_pasados,
                                 "ultimo_pago": r["ultimo_pago"]})
        if vencidos:
            alertas.append({
                "tipo": "recurrente_vencido",
                "severidad": "media",
                "titulo": f"{len(vencidos)} pagos recurrentes sin registrar hace rato",
                "detalle": "Llevan más de dos periodos sin un pago registrado.",
                "items": sorted(vencidos, key=lambda v: -v["dias"]),
            })
    except Exception:
        pass

    return alertas


# --------------------------------------------------------------------------- #
# Salidas
# --------------------------------------------------------------------------- #
def imprimir(inf: dict) -> None:
    t = inf["total"]
    print()
    print(f"  UTILIDAD  {inf['desde']}  ->  {inf['hasta']}")
    print(f"  (jornada con corte a las {inf['corte_jornada']}:00; la madrugada cuenta para la noche anterior)")
    print()
    print(f"  {'MES':<9}{'VENTAS':>15}{'COMPRAS':>14}{'GASTOS':>14}{'UTILIDAD':>15}"
          f"{'MARGEN':>9}{'SAL/VTA':>9}")
    print("  " + "-" * 85)
    for f in inf["periodos"]:
        print(f"  {f['periodo']:<9}{pesos(f['ventas']):>15}{pesos(f['compras']):>14}"
              f"{pesos(f['gastos']):>14}{pesos(f['utilidad']):>15}{f['margen']:>8.0f}%"
              f"{f['peso_salidas']:>8.0f}%")
    print("  " + "-" * 85)
    print(f"  {'TOTAL':<9}{pesos(t['ventas']):>15}{pesos(t['compras']):>14}"
          f"{pesos(t['gastos']):>14}{pesos(t['utilidad']):>15}{t['margen']:>8.0f}%"
          f"{(t['salidas']/t['ventas']*100 if t['ventas'] else 0):>8.0f}%")
    print()
    print("  SAL/VTA = cuánto pesan compras+gastos sobre la venta. Un mes muy por")
    print("  debajo de los demás suele ser un mes al que le faltan registros.")
    print()
    print(f"  {t['n_facturas']} facturas · {t['n_compras']} compras · {t['n_gastos']} gastos")

    if inf["alertas"]:
        print()
        print("  REVISAR — posibles registros faltantes")
        print("  " + "-" * 76)
        for a in inf["alertas"]:
            marca = "!!" if a["severidad"] == "alta" else " ·"
            print(f"  {marca} {a['titulo']}")
            print(f"     {a['detalle']}")
            for it in (a.get("items") or [])[:6]:
                if isinstance(it, dict) and "concepto" in it:
                    print(f"       - {it['fecha']}  {pesos(it['monto']):>12}  {it['concepto'][:34]}"
                          f"  (registrado {it['registrado']})")
                elif isinstance(it, dict):
                    print(f"       - {it['nombre']}: hace {it['dias']} días ({it['ultimo_pago']})")
                else:
                    print(f"       - {it}")
            resto = len(a.get("items") or []) - 6
            if resto > 0:
                print(f"       … y {resto} más")
    print()


def escribir_csv(inf: dict, ruta: Path) -> None:
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Mes", "Ventas", "Compras", "Gastos", "Salidas", "Utilidad",
                    "Margen %", "Salidas/Ventas %", "Facturas", "N compras", "N gastos"])
        for f in inf["periodos"]:
            w.writerow([f["periodo"], round(f["ventas"]), round(f["compras"]), round(f["gastos"]),
                        round(f["salidas"]), round(f["utilidad"]), round(f["margen"], 1),
                        round(f["peso_salidas"], 1), f["n_facturas"], f["n_compras"], f["n_gastos"]])
        t = inf["total"]
        w.writerow(["TOTAL", round(t["ventas"]), round(t["compras"]), round(t["gastos"]),
                    round(t["salidas"]), round(t["utilidad"]), round(t["margen"], 1), "",
                    t["n_facturas"], t["n_compras"], t["n_gastos"]])
        if inf["alertas"]:
            w.writerow([])
            w.writerow(["REVISAR", "Detalle"])
            for a in inf["alertas"]:
                w.writerow([a["titulo"], a["detalle"]])
    print(f"  CSV  -> {ruta}")


def escribir_html(inf: dict, ruta: Path) -> None:
    e = html.escape
    t = inf["total"]
    filas = "\n".join(
        f"<tr><td>{f['periodo']}</td><td class=n>{pesos(f['ventas'])}</td>"
        f"<td class=n>{pesos(f['compras'])}</td><td class=n>{pesos(f['gastos'])}</td>"
        f"<td class='n {'neg' if f['utilidad'] < 0 else 'pos'}'>{pesos(f['utilidad'])}</td>"
        f"<td class=n>{f['margen']:.0f}%</td></tr>"
        for f in inf["periodos"]
    )
    alertas = "".join(
        f"<div class='al {a['severidad']}'><b>{e(a['titulo'])}</b><br><small>{e(a['detalle'])}</small></div>"
        for a in inf["alertas"]
    )
    ruta.write_text(f"""<!doctype html><meta charset=utf-8>
<title>Utilidad {inf['desde']} a {inf['hasta']}</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;margin:2rem auto;max-width:900px;color:#1a1a1a}}
 h1{{font-size:1.4rem;margin-bottom:.2rem}} .sub{{color:#666;font-size:.85rem;margin-bottom:1.5rem}}
 table{{border-collapse:collapse;width:100%}} th,td{{padding:.5rem .6rem;border-bottom:1px solid #e5e5e5}}
 th{{text-align:left;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:#666}}
 .n{{text-align:right;font-variant-numeric:tabular-nums}} .pos{{color:#0a7d4b}} .neg{{color:#c2415a}}
 tfoot td{{font-weight:700;border-top:2px solid #1a1a1a}}
 .al{{padding:.7rem .9rem;border-radius:8px;margin:.5rem 0;font-size:.9rem}}
 .al.alta{{background:#fdecea;border-left:4px solid #c2415a}}
 .al.media{{background:#fff6e5;border-left:4px solid #e8a23a}}
</style>
<h1>Utilidad · {inf['desde']} a {inf['hasta']}</h1>
<div class=sub>Ventas menos compras y gastos. Jornada con corte a las {inf['corte_jornada']}:00.</div>
<table>
 <thead><tr><th>Mes</th><th class=n>Ventas</th><th class=n>Compras</th>
 <th class=n>Gastos</th><th class=n>Utilidad</th><th class=n>Margen</th></tr></thead>
 <tbody>{filas}</tbody>
 <tfoot><tr><td>TOTAL</td><td class=n>{pesos(t['ventas'])}</td><td class=n>{pesos(t['compras'])}</td>
 <td class=n>{pesos(t['gastos'])}</td><td class=n>{pesos(t['utilidad'])}</td>
 <td class=n>{t['margen']:.0f}%</td></tr></tfoot>
</table>
{'<h2 style=font-size:1.05rem;margin-top:2rem>Revisar</h2>' + alertas if alertas else ''}
""", encoding="utf-8")
    print(f"  HTML -> {ruta}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Informe de utilidad: ventas vs compras y gastos.")
    ap.add_argument("--desde", help="Fecha inicial YYYY-MM-DD (por defecto: --meses hacia atrás).")
    ap.add_argument("--hasta", help="Fecha final YYYY-MM-DD (por defecto: hoy).")
    ap.add_argument("--meses", type=int, default=6, help="Meses hacia atrás si no se da --desde.")
    ap.add_argument("--html", action="store_true", help="Además escribe informe_utilidad.html.")
    args = ap.parse_args()

    hasta = dt.date.fromisoformat(args.hasta) if args.hasta else dt.date.today()
    if args.desde:
        desde = dt.date.fromisoformat(args.desde)
    else:
        m = hasta.month - args.meses
        desde = dt.date(hasta.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)

    cli = LoggroClient()
    cli.login()
    print(f"  Consultando Loggro ({desde} a {hasta})…")
    inf = agrupar(traer(cli, desde, hasta), desde, hasta)

    imprimir(inf)
    escribir_csv(inf, CSV_SALIDA)
    if args.html:
        escribir_html(inf, HTML_SALIDA)


if __name__ == "__main__":
    main()
