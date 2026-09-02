import { useEffect, useMemo, useState } from "react";
import { api, type AlertaUtilidad, type PeriodoUtilidad, type UtilidadResult } from "../api";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

/** Compacto para las barras y los totales grandes: $42,2 M. */
function corto(v: number): string {
  const a = Math.abs(v);
  if (a >= 1_000_000) return `${v < 0 ? "-" : ""}$${(a / 1_000_000).toFixed(1)} M`;
  if (a >= 1_000) return `${v < 0 ? "-" : ""}$${Math.round(a / 1_000)} k`;
  return cop.format(v);
}

const MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/** "2026-08" -> "ago 2026" */
function nombreMes(periodo: string): string {
  const [a, m] = periodo.split("-");
  return `${MES[Number(m) - 1] ?? m} ${a}`;
}

const RANGOS = [
  { meses: 3, etiqueta: "3 meses" },
  { meses: 6, etiqueta: "6 meses" },
  { meses: 12, etiqueta: "12 meses" },
];

/**
 * Utilidad: ventas contra salidas (compras + gastos), mes a mes.
 *
 * Es utilidad de CAJA, no contable: se restan las compras del periodo, no el
 * costo de lo vendido. El costo por producto en Loggro está cargado en menos de
 * la mitad de la venta, así que un margen calculado con él mentiría.
 *
 * Todo el cálculo vive en informe_utilidad.py, el mismo módulo que usan la
 * consola y el CSV, para que las cifras no se puedan desincronizar.
 */
export default function UtilidadView() {
  const [data, setData] = useState<UtilidadResult | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [meses, setMeses] = useState(6);

  useEffect(() => {
    setCargando(true);
    setError(null);
    api
      .utilidad({ meses })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setCargando(false));
  }, [meses]);

  // Escala común para las barras: si cada mes se normalizara a sí mismo,
  // un mes flojo se vería igual de alto que el mejor.
  const tope = useMemo(
    () => Math.max(1, ...(data?.periodos ?? []).map((p) => p.ventas)),
    [data]
  );

  if (cargando && !data) {
    return <p className="py-16 text-center text-sm text-sand-500">Calculando utilidad…</p>;
  }
  if (error) {
    return (
      <p className="rounded-xl border border-pending/40 bg-pending/10 px-4 py-3 text-sm text-pending">
        {error}
      </p>
    );
  }
  if (!data) return null;

  const t = data.total;
  const perdida = t.utilidad < 0;

  return (
    <div className="grid gap-6">
      {/* Encabezado con el resultado del periodo completo */}
      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-6 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-amber">
              {perdida ? "Pérdida del periodo" : "Utilidad del periodo"}
            </p>
            <p
              className={`mt-2 font-display text-4xl font-bold ${
                perdida ? "text-pending" : "text-matched"
              }`}
            >
              {cop.format(t.utilidad)}
            </p>
            <p className="mt-1 text-xs text-sand-500">
              {data.desde} a {data.hasta} · margen {t.margen.toFixed(0)}% ·{" "}
              {t.n_facturas.toLocaleString("es-CO")} facturas
            </p>
          </div>
          <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5 text-xs">
            {RANGOS.map((r) => (
              <button
                key={r.meses}
                onClick={() => setMeses(r.meses)}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  meses === r.meses ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
                }`}
              >
                {r.etiqueta}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Dato etiqueta="Ventas" valor={t.ventas} color="text-sand-50" />
          <Dato etiqueta="Compras" valor={t.compras} color="text-sand-300" sub={`${t.n_compras} movs`} />
          <Dato etiqueta="Gastos" valor={t.gastos} color="text-sand-300" sub={`${t.n_gastos} registros`} />
          <Dato
            etiqueta="Salidas / ventas"
            texto={`${((t.salidas / (t.ventas || 1)) * 100).toFixed(0)}%`}
            color="text-amber"
          />
        </div>
      </section>

      {/* Avisos de información incompleta */}
      {data.alertas.length > 0 && (
        <section className="grid gap-2">
          {data.alertas.map((a, i) => (
            <Alerta key={`${a.tipo}-${a.periodo ?? i}`} alerta={a} />
          ))}
        </section>
      )}

      {/* Mes a mes */}
      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel [animation-delay:80ms]">
        <div className="border-b border-espresso-700 px-5 py-4">
          <h2 className="font-display text-lg font-semibold text-sand-50">Mes a mes</h2>
          <p className="mt-0.5 text-xs text-sand-500">
            La barra es la venta; el relleno, lo que se fue en compras y gastos. Lo que sobra
            de la barra es la utilidad.
          </p>
        </div>
        <ul>
          {data.periodos.map((p, i) => (
            <FilaMes key={p.periodo} p={p} tope={tope} indice={i} />
          ))}
        </ul>
      </section>

      <p className="text-center text-[11px] leading-relaxed text-sand-500/70">
        Utilidad de caja: ventas menos compras y gastos del mes, no costo de lo vendido.
        <br />
        La jornada corta a las {data.corte_jornada}:00, así que la madrugada cuenta para la noche
        anterior. Las propinas no son ingreso y quedan fuera.
      </p>
    </div>
  );
}

function Dato({
  etiqueta,
  valor,
  texto,
  color,
  sub,
}: {
  etiqueta: string;
  valor?: number;
  texto?: string;
  color: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-espresso-700 bg-espresso-950/40 px-3 py-2.5">
      <p className="font-mono text-[10px] uppercase tracking-wider text-sand-500">{etiqueta}</p>
      <p className={`mt-1 font-display text-lg font-bold ${color}`}>
        {texto ?? corto(valor ?? 0)}
      </p>
      {sub && <p className="text-[10px] text-sand-500/70">{sub}</p>}
    </div>
  );
}

function FilaMes({ p, tope, indice }: { p: PeriodoUtilidad; tope: number; indice: number }) {
  const [abierto, setAbierto] = useState(false);
  const perdida = p.utilidad < 0;
  const anchoVenta = (p.ventas / tope) * 100;
  // Proporciones DENTRO de la barra de venta, para que compras+gastos+utilidad
  // sumen exactamente el ancho de la venta.
  const pctCompras = p.ventas ? (p.compras / p.ventas) * 100 : 0;
  const pctGastos = p.ventas ? (p.gastos / p.ventas) * 100 : 0;

  return (
    <li
      className="animate-fade border-b border-dashed border-espresso-700 last:border-b-0"
      style={{ animationDelay: `${Math.min(indice, 12) * 40}ms` }}
    >
      <button
        onClick={() => setAbierto((v) => !v)}
        aria-expanded={abierto}
        className="w-full px-5 py-4 text-left transition hover:bg-espresso-850/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber"
      >
        <div className="flex items-baseline justify-between gap-4">
          <span className="font-display text-sm font-semibold capitalize text-sand-100">
            {nombreMes(p.periodo)}
          </span>
          <span className="flex items-baseline gap-3">
            <span className="font-mono text-[11px] text-sand-500">{corto(p.ventas)} vendidos</span>
            <span
              className={`font-mono text-sm font-bold ${perdida ? "text-pending" : "text-matched"}`}
            >
              {corto(p.utilidad)}
            </span>
            <span className="w-9 text-right font-mono text-[11px] text-sand-500">
              {p.margen.toFixed(0)}%
            </span>
          </span>
        </div>

        <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-espresso-950/60">
          <div className="flex h-full" style={{ width: `${anchoVenta}%` }}>
            <div
              className="h-full bg-amber-deep"
              style={{ width: `${pctCompras}%` }}
              title={`Compras ${cop.format(p.compras)}`}
            />
            <div
              className="h-full bg-amber"
              style={{ width: `${pctGastos}%` }}
              title={`Gastos ${cop.format(p.gastos)}`}
            />
            <div
              className={`h-full flex-1 ${perdida ? "bg-pending" : "bg-matched"}`}
              title={`Utilidad ${cop.format(p.utilidad)}`}
            />
          </div>
        </div>
      </button>

      {abierto && (
        <div className="animate-fade border-t border-dashed border-espresso-700 bg-espresso-950/40 px-5 py-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <Detalle t="Ventas" v={cop.format(p.ventas)} sub={`${p.n_facturas} facturas`} />
            <Detalle t="Compras" v={cop.format(p.compras)} sub={`${p.n_compras} movimientos`} />
            <Detalle t="Gastos" v={cop.format(p.gastos)} sub={`${p.n_gastos} registros`} />
            <Detalle
              t="Salidas / ventas"
              v={`${p.peso_salidas.toFixed(0)}%`}
              sub="entre más bajo, más sospechoso"
            />
          </dl>
        </div>
      )}
    </li>
  );
}

function Detalle({ t, v, sub }: { t: string; v: string; sub: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-wider text-sand-500">{t}</dt>
      <dd className="mt-0.5 font-mono text-sand-100">{v}</dd>
      <dd className="text-[10px] text-sand-500/70">{sub}</dd>
    </div>
  );
}

function Alerta({ alerta: a }: { alerta: AlertaUtilidad }) {
  const [abierto, setAbierto] = useState(false);
  const alta = a.severidad === "alta";
  const items = a.items ?? [];

  return (
    <div
      className={`animate-rise rounded-xl border px-4 py-3 ${
        alta ? "border-pending/50 bg-pending/10" : "border-amber/40 bg-amber/5"
      }`}
    >
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 shrink-0 ${alta ? "text-pending" : "text-amber"}`} aria-hidden>
          {alta ? "▲" : "•"}
        </span>
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-semibold ${alta ? "text-pending" : "text-amber-bright"}`}>
            {a.titulo}
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-sand-400">{a.detalle}</p>

          {items.length > 0 && (
            <>
              <button
                onClick={() => setAbierto((v) => !v)}
                className="mt-1.5 font-mono text-[11px] uppercase tracking-wider text-sand-500 transition hover:text-sand-200"
              >
                {abierto ? "ocultar" : `ver ${items.length}`}
              </button>
              {abierto && (
                <ul className="mt-2 grid gap-1 border-t border-dashed border-espresso-700 pt-2">
                  {items.map((it, i) => (
                    <li key={i} className="font-mono text-[11px] text-sand-400">
                      {typeof it === "string" ? it : describir(it)}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** Los items varían según la alerta; se arma la línea con lo que traiga. */
function describir(it: Record<string, string | number>): string {
  if ("concepto" in it) {
    return `${it.fecha} · ${cop.format(Number(it.monto))} · ${it.concepto} (registrado ${it.registrado})`;
  }
  if ("nombre" in it) return `${it.nombre} · hace ${it.dias} días (${it.ultimo_pago})`;
  return Object.values(it).join(" · ");
}
