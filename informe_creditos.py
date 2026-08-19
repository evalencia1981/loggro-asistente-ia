"""
informe_creditos.py
Informe de cartera: cuánto debe cada cliente en Loggro Restobar.

Fuente de datos: GET /invoices?status=Por Pagar (facturas a crédito). La deuda de
cada factura es `total - totalPaid`, la misma fórmula que usa el Excel de la web
de Loggro. Ver `LoggroClient.get_credit_invoices`.

Uso:
    python -X utf8 informe_creditos.py                 # todo el histórico
    python -X utf8 informe_creditos.py --desde 2026-01-01
    python -X utf8 informe_creditos.py --detalle       # + factura por factura
    python -X utf8 informe_creditos.py --html          # + informe_creditos.html

Siempre escribe `informe_creditos.csv` (abrible en Excel) junto al script.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
from collections import defaultdict
from pathlib import Path

from loggro_client import LoggroClient

RAIZ = Path(__file__).parent
CSV_SALIDA = RAIZ / "informe_creditos.csv"
HTML_SALIDA = RAIZ / "informe_creditos.html"

# Tramos de antigüedad de la deuda, en días desde el vencimiento.
# "Por vencer" = plazo aún vigente (dueDate en el futuro), no es mora.
TRAMOS = [("Por vencer", -(10**6), -1), ("1-30", 0, 30), ("31-60", 31, 60),
          ("61-90", 61, 90), ("+91", 91, 10**6)]


def pesos(v: float) -> str:
    """35000 -> '$35.000' (formato colombiano)."""
    return "$" + f"{round(v):,}".replace(",", ".")


def fecha_de(inv: dict) -> dt.date:
    """Fecha desde la que se cuenta la antigüedad: el vencimiento si existe, si no la factura."""
    crudo = (inv.get("credit") or {}).get("dueDate") or inv.get("createdOn") or ""
    try:
        return dt.datetime.fromisoformat(crudo.replace("Z", "+00:00")).date()
    except ValueError:
        return dt.date.today()


def nombre_de(cliente: dict) -> str:
    return f"{cliente.get('name', '') or ''} {cliente.get('lastName', '') or ''}".strip() or "(sin nombre)"


def agrupar(facturas: list[dict], hoy: dt.date, catalogo: dict[str, dict]) -> list[dict]:
    """Facturas -> una fila por cliente, con saldo y desglose por antigüedad.

    Se agrupa por `client.idInternal`, que es el `_id` del cliente en /clients:
    la factura solo guarda una copia de los datos del cliente al momento de
    venderla, y hay documentos repetidos entre clientes distintos (cédulas
    tipo "12345") y clientes a los que les cambiaron el nombre después. Por eso
    el nombre se toma del catálogo actual, no de la factura.
    """
    por_cliente: dict[str, dict] = {}
    for inv in facturas:
        snap = inv.get("client") or {}
        clave = snap.get("idInternal") or snap.get("document") or nombre_de(snap)
        cli = catalogo.get(clave) or snap
        fila = por_cliente.setdefault(clave, {
            "cliente": nombre_de(cli),
            "documento": cli.get("document", "") or "",
            "telefono": cli.get("phone", "") or "",
            "facturas": 0, "total": 0, "abonado": 0, "saldo": 0,
            "dias_mas_vieja": 0,
            "tramos": defaultdict(int),
            "detalle": [],
        })

        saldo = (inv.get("total") or 0) - (inv.get("totalPaid") or 0)
        if saldo <= 0:
            continue  # factura de crédito ya saldada: no es cartera

        dias = (hoy - fecha_de(inv)).days
        fila["facturas"] += 1
        fila["total"] += inv.get("total") or 0
        fila["abonado"] += inv.get("totalPaid") or 0
        fila["saldo"] += saldo
        fila["dias_mas_vieja"] = max(fila["dias_mas_vieja"], dias)
        for etiqueta, desde, hasta in TRAMOS:
            if desde <= dias <= hasta:
                fila["tramos"][etiqueta] += saldo
                break
        fila["detalle"].append({
            "numero": inv.get("number", ""),
            "fecha": fecha_de(inv).isoformat(),
            "dias": dias,
            "total": inv.get("total") or 0,
            "abonado": inv.get("totalPaid") or 0,
            "saldo": saldo,
            "cuotas": (inv.get("credit") or {}).get("dueQuote") or 1,
        })

    filas = [f for f in por_cliente.values() if f["saldo"] > 0]
    filas.sort(key=lambda f: f["saldo"], reverse=True)
    for f in filas:
        f["detalle"].sort(key=lambda d: d["fecha"])
    return filas


def imprimir(filas: list[dict], detalle: bool) -> None:
    ancho = 112
    print("=" * ancho)
    print(f"{'CLIENTE':<32}{'DOCUMENTO':<14}{'FACT':>5}{'TOTAL':>14}{'ABONADO':>14}{'SALDO':>14}{'MAS VIEJA':>12}")
    print("=" * ancho)
    for f in filas:
        print(f"{f['cliente'][:31]:<32}{f['documento'][:13]:<14}{f['facturas']:>5}"
              f"{pesos(f['total']):>14}{pesos(f['abonado']):>14}{pesos(f['saldo']):>14}"
              f"{str(f['dias_mas_vieja']) + ' d':>12}")
        if detalle:
            for d in f["detalle"]:
                print(f"      {d['numero']:<12}{d['fecha']:<12}{str(d['dias']) + ' d':>7}"
                      f"{pesos(d['total']):>14}{pesos(d['abonado']):>14}{pesos(d['saldo']):>14}")
    print("=" * ancho)
    print(f"{'TOTAL':<32}{'':<14}{sum(f['facturas'] for f in filas):>5}"
          f"{pesos(sum(f['total'] for f in filas)):>14}"
          f"{pesos(sum(f['abonado'] for f in filas)):>14}"
          f"{pesos(sum(f['saldo'] for f in filas)):>14}")
    print(f"\n{len(filas)} clientes con deuda.")

    print("\nCartera por antigüedad (días desde el vencimiento):")
    for etiqueta, _, _ in TRAMOS:
        monto = sum(f["tramos"].get(etiqueta, 0) for f in filas)
        sufijo = "" if etiqueta == "Por vencer" else " días"
        print(f"  {etiqueta + sufijo:>16}: {pesos(monto):>16}")


def escribir_csv(filas: list[dict], ruta: Path) -> None:
    cols = ["cliente", "documento", "telefono", "facturas", "total", "abonado", "saldo", "dias_mas_vieja"]
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel lee bien los acentos
        w = csv.writer(f, delimiter=";")
        w.writerow(["Cliente", "Documento", "Teléfono", "Facturas", "Total", "Abonado", "Saldo",
                    "Días más vieja", *[f"{t[0]} días" for t in TRAMOS]])
        for fila in filas:
            w.writerow([*[fila[c] for c in cols], *[fila["tramos"].get(t[0], 0) for t in TRAMOS]])
        w.writerow([])
        w.writerow(["TOTAL", "", "", sum(f["facturas"] for f in filas),
                    sum(f["total"] for f in filas), sum(f["abonado"] for f in filas),
                    sum(f["saldo"] for f in filas)])


def escribir_html(filas: list[dict], ruta: Path, hoy: dt.date) -> None:
    e = html.escape
    tramos_head = "".join(f"<th class='num'>{t[0]} días</th>" for t in TRAMOS)
    cuerpo = []
    for f in filas:
        tramos_td = "".join(f"<td class='num'>{pesos(f['tramos'][t[0]]) if f['tramos'].get(t[0]) else '—'}</td>"
                            for t in TRAMOS)
        cuerpo.append(
            f"<tr><td>{e(f['cliente'])}</td><td>{e(f['documento'])}</td><td>{e(f['telefono'])}</td>"
            f"<td class='num'>{f['facturas']}</td><td class='num'>{pesos(f['total'])}</td>"
            f"<td class='num'>{pesos(f['abonado'])}</td><td class='num saldo'>{pesos(f['saldo'])}</td>"
            f"<td class='num'>{f['dias_mas_vieja']} d</td>{tramos_td}</tr>")
    total_saldo = sum(f["saldo"] for f in filas)
    ruta.write_text(f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Cartera de clientes — Loggro Restobar</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#1a1a1a}}
 h1{{margin:0 0 .25rem;font-size:1.4rem}} .sub{{color:#666;margin-bottom:1.5rem}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{padding:.45rem .6rem;border-bottom:1px solid #e5e5e5;text-align:left}}
 th{{background:#f6f6f6;font-weight:600;white-space:nowrap}}
 .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
 .saldo{{font-weight:600}} tr:hover td{{background:#fafafa}}
 .tot{{font-size:1.6rem;font-weight:700;margin:.5rem 0 1.5rem}}
</style></head><body>
<h1>Cartera de clientes — Loggro Restobar</h1>
<div class="sub">Generado el {hoy.isoformat()} · {len(filas)} clientes con deuda</div>
<div class="tot">{pesos(total_saldo)}</div>
<table><thead><tr><th>Cliente</th><th>Documento</th><th>Teléfono</th><th class="num">Fact.</th>
<th class="num">Total</th><th class="num">Abonado</th><th class="num">Saldo</th><th class="num">Más vieja</th>
{tramos_head}</tr></thead><tbody>
{chr(10).join(cuerpo)}
</tbody></table></body></html>""", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Informe de deuda por cliente (Loggro Restobar)")
    p.add_argument("--desde", default="2020-01-01", help="fecha inicial YYYY-MM-DD")
    p.add_argument("--hasta", default=None, help="fecha final YYYY-MM-DD (por defecto, hoy)")
    p.add_argument("--detalle", action="store_true", help="listar también cada factura")
    p.add_argument("--html", action="store_true", help="generar informe_creditos.html")
    args = p.parse_args()

    hoy = dt.date.today()
    hasta = dt.date.fromisoformat(args.hasta) if args.hasta else hoy
    desde_iso = f"{args.desde}T00:00:00.000Z"
    hasta_iso = f"{(hasta + dt.timedelta(days=1)).isoformat()}T00:00:00.000Z"

    cli = LoggroClient()
    cli.login()
    facturas = cli.get_credit_invoices(desde_iso, hasta_iso)
    clientes = cli._get("/clients")
    catalogo = {c["_id"]: c for c in (clientes.get("data", clientes) if isinstance(clientes, dict) else clientes)}
    print(f"{len(facturas)} facturas a crédito entre {args.desde} y {hasta.isoformat()}.\n")

    filas = agrupar(facturas, hoy, catalogo)
    imprimir(filas, args.detalle)

    escribir_csv(filas, CSV_SALIDA)
    print(f"\nCSV: {CSV_SALIDA}")
    if args.html:
        escribir_html(filas, HTML_SALIDA, hoy)
        print(f"HTML: {HTML_SALIDA}")


if __name__ == "__main__":
    main()
