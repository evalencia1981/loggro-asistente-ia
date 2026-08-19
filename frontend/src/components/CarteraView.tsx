import { useEffect, useMemo, useState } from "react";
import { api, type CarteraResult, type CreditoCliente } from "../api";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

// Escala de antigüedad. "Por vencer" es un estado aparte (aún no es mora); los
// cuatro tramos de mora refuerzan el orden con intensidad creciente. La etiqueta
// siempre acompaña al color: nunca se identifica un tramo por el color solo.
const COLOR_TRAMO: Record<string, string> = {
  "Por vencer": "#5fb98e",
  "1-30": "#f5c563",
  "31-60": "#e8a23a",
  "61-90": "#e8804f",
  "+91": "#c2415a",
};

const ETIQUETA_TRAMO: Record<string, string> = {
  "Por vencer": "Por vencer",
  "1-30": "1 a 30 días",
  "31-60": "31 a 60 días",
  "61-90": "61 a 90 días",
  "+91": "Más de 91 días",
};

/** Estado de cobro de un cliente, por la factura más vieja que tenga sin pagar. */
function estado(dias: number): { texto: string; color: string; fondo: string } {
  if (dias < 0) return { texto: "al día", color: "#5fb98e", fondo: "rgba(95,185,142,0.14)" };
  if (dias <= 90) return { texto: `${dias} d de mora`, color: "#e8a23a", fondo: "rgba(232,162,58,0.14)" };
  return { texto: `${dias} d de mora`, color: "#c2415a", fondo: "rgba(194,65,90,0.18)" };
}

function fechaLarga(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" });
}

function descargarCSV(data: CarteraResult) {
  const cab = ["Cliente", "Documento", "Teléfono", "Cuentas", "Facturado", "Abonado", "Saldo",
    "Días de mora", ...data.tramos.map((t) => ETIQUETA_TRAMO[t.etiqueta] ?? t.etiqueta)];
  const filas = data.detalle.map((c) => [
    c.cliente, c.documento, c.telefono, c.facturas, c.total, c.abonado, c.saldo,
    c.dias_mas_vieja, ...data.tramos.map((t) => c.tramos[t.etiqueta] ?? 0),
  ]);
  const csv = [cab, ...filas]
    .map((f) => f.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";"))
    .join("\n");
  const url = URL.createObjectURL(new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `cartera-${data.generado}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CarteraView() {
  const [data, setData] = useState<CarteraResult | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState("");
  const [orden, setOrden] = useState<"saldo" | "mora" | "nombre">("saldo");
  const [abierto, setAbierto] = useState<string | null>(null);

  const cargar = () => {
    setCargando(true);
    setError(null);
    api
      .creditos()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setCargando(false));
  };

  useEffect(cargar, []);

  const clientes = useMemo(() => {
    if (!data) return [];
    const q = busqueda.trim().toLowerCase();
    const filtrados = q
      ? data.detalle.filter(
          (c) => c.cliente.toLowerCase().includes(q) || c.documento.toLowerCase().includes(q)
        )
      : data.detalle;
    const orden_ = [...filtrados];
    if (orden === "saldo") orden_.sort((a, b) => b.saldo - a.saldo);
    if (orden === "mora") orden_.sort((a, b) => b.dias_mas_vieja - a.dias_mas_vieja);
    if (orden === "nombre") orden_.sort((a, b) => a.cliente.localeCompare(b.cliente, "es"));
    return orden_;
  }, [data, busqueda, orden]);

  if (cargando) {
    return (
      <div className="flex min-h-[300px] animate-fade items-center justify-center rounded-2xl border border-dashed border-espresso-700 bg-espresso-900/30">
        <p className="text-sm text-sand-500">Consultando los créditos en Loggro…</p>
      </div>
    );
  }

  if (error) {
    return (
      <p className="rounded-xl border border-pending/40 bg-pending/10 px-4 py-3 text-sm text-pending">
        {error}
      </p>
    );
  }

  if (!data) return null;

  const maxTramo = Math.max(...data.tramos.map((t) => t.monto), 1);
  const saldoMayor = clientes.length ? Math.max(...clientes.map((c) => c.saldo)) : 1;

  return (
    <div className="space-y-6">
      {/* ---------- Resumen ---------- */}
      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel">
        <div className="grid gap-8 p-6 md:grid-cols-12 md:p-8">
          {/* Total */}
          <div className="md:col-span-5">
            <div className="flex items-center justify-between gap-3">
              <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-amber">
                Cartera
              </p>
              <button
                onClick={cargar}
                className="rounded-full border border-espresso-600 px-3 py-1 text-[11px] font-semibold text-sand-400 transition hover:border-amber hover:text-amber focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
              >
                Actualizar
              </button>
            </div>
            <p className="mt-3 font-display text-4xl font-extrabold leading-none text-sand-50 md:text-5xl">
              {cop.format(data.saldo)}
            </p>
            <p className="mt-3 text-sm text-sand-400">
              Le deben {data.clientes} clientes en {data.facturas} cuentas abiertas.
            </p>
            <p className="mt-1 text-xs text-sand-500">
              Han abonado {cop.format(data.abonado)} de {cop.format(data.facturado)} fiados ·
              al {fechaLarga(data.generado)}
            </p>
            <button
              onClick={() => descargarCSV(data)}
              className="mt-5 inline-flex items-center gap-2 rounded-xl border border-espresso-600 bg-espresso-850 px-4 py-2 text-xs font-semibold text-sand-100 transition hover:border-amber hover:text-amber focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
              </svg>
              Descargar en Excel
            </button>
          </div>

          {/* Antigüedad */}
          <div className="md:col-span-7">
            <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-sand-500">
              Antigüedad de la deuda
            </p>
            <ul className="mt-4 space-y-3">
              {data.tramos.map((t, i) => {
                const pct = data.saldo ? (t.monto / data.saldo) * 100 : 0;
                return (
                  <li
                    key={t.etiqueta}
                    className="animate-fade grid grid-cols-[8.5rem_1fr_auto] items-center gap-3"
                    style={{ animationDelay: `${120 + i * 70}ms` }}
                  >
                    <span className="text-xs text-sand-400">
                      {ETIQUETA_TRAMO[t.etiqueta] ?? t.etiqueta}
                    </span>
                    <span className="h-2.5 w-full overflow-hidden rounded-full bg-espresso-800">
                      <span
                        className="block h-full origin-left animate-pour rounded-r-[4px]"
                        style={{
                          width: `${(t.monto / maxTramo) * 100}%`,
                          backgroundColor: COLOR_TRAMO[t.etiqueta] ?? "#e8a23a",
                          animationDelay: `${180 + i * 70}ms`,
                        }}
                      />
                    </span>
                    <span className="text-right font-mono text-xs tabular-nums text-sand-200">
                      {cop.format(t.monto)}
                      <span className="ml-2 text-sand-500">{Math.round(pct)}%</span>
                    </span>
                  </li>
                );
              })}
            </ul>
            <p className="mt-4 text-xs text-sand-500">
              Los días se cuentan desde la fecha límite de pago de cada factura.
            </p>
          </div>
        </div>
      </section>

      {/* ---------- Filtros ---------- */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative sm:max-w-xs sm:flex-1">
          <svg
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-sand-500"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar por nombre o cédula"
            className="w-full rounded-xl border border-espresso-600 bg-espresso-900/70 py-2.5 pl-9 pr-3 text-sm text-sand-50 outline-none transition placeholder:text-sand-500/60 focus:border-amber focus:shadow-glow"
          />
        </div>
        <div className="inline-flex rounded-xl border border-espresso-600 bg-espresso-950/50 p-1 text-xs">
          {([
            ["saldo", "Mayor deuda"],
            ["mora", "Más atrasado"],
            ["nombre", "Por nombre"],
          ] as const).map(([v, label]) => (
            <button
              key={v}
              onClick={() => setOrden(v)}
              className={`rounded-lg px-3.5 py-1.5 font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-amber ${
                orden === v ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ---------- Clientes ---------- */}
      {clientes.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-espresso-700 bg-espresso-900/30 p-10 text-center text-sm text-sand-500">
          Ningún cliente coincide con “{busqueda}”.
        </p>
      ) : (
        <ul className="overflow-hidden rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel">
          {clientes.map((c, i) => (
            <FilaCliente
              key={`${c.documento}-${c.cliente}-${i}`}
              cliente={c}
              indice={i}
              proporcion={c.saldo / saldoMayor}
              abierto={abierto === `${c.documento}-${c.cliente}`}
              onToggle={() =>
                setAbierto((a) =>
                  a === `${c.documento}-${c.cliente}` ? null : `${c.documento}-${c.cliente}`
                )
              }
            />
          ))}
        </ul>
      )}

      <p className="text-center font-mono text-[11px] uppercase tracking-[0.25em] text-sand-500/60">
        {clientes.length} de {data.clientes} clientes
      </p>
    </div>
  );
}

function FilaCliente({
  cliente: c,
  indice,
  proporcion,
  abierto,
  onToggle,
}: {
  cliente: CreditoCliente;
  indice: number;
  proporcion: number;
  abierto: boolean;
  onToggle: () => void;
}) {
  const est = estado(c.dias_mas_vieja);
  return (
    <li
      className="animate-fade border-b border-dashed border-espresso-700 last:border-b-0"
      style={{ animationDelay: `${Math.min(indice, 12) * 35}ms` }}
    >
      <button
        onClick={onToggle}
        aria-expanded={abierto}
        className="group w-full px-5 py-4 text-left transition hover:bg-espresso-850/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber"
      >
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="flex items-center gap-2 truncate font-display text-base font-semibold text-sand-50">
              <svg
                className={`h-3 w-3 shrink-0 text-sand-500 transition-transform ${abierto ? "rotate-90" : ""}`}
                viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
              >
                <path d="m9 6 6 6-6 6" />
              </svg>
              {c.cliente}
            </p>
            <p className="mt-0.5 truncate pl-5 font-mono text-[11px] text-sand-500">
              {c.documento || "sin cédula"}
              {c.telefono ? ` · ${c.telefono}` : ""} · {c.facturas}{" "}
              {c.facturas === 1 ? "cuenta" : "cuentas"}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <p className="font-mono text-base tabular-nums text-sand-50">{cop.format(c.saldo)}</p>
            <span
              className="mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
              style={{ color: est.color, backgroundColor: est.fondo }}
            >
              {est.texto}
            </span>
          </div>
        </div>
        {/* Peso de este cliente dentro de la cartera */}
        <span className="mt-3 block h-1 w-full overflow-hidden rounded-full bg-espresso-800">
          <span
            className="block h-full rounded-r-[4px] bg-gradient-to-r from-amber-deep to-amber transition-[width] duration-500"
            style={{ width: `${Math.max(proporcion * 100, 1.5)}%` }}
          />
        </span>
      </button>

      {abierto && (
        <div className="animate-fade border-t border-dashed border-espresso-700 bg-espresso-950/40 px-5 py-4">
          <div className="flex justify-between gap-4 text-[11px] text-sand-500 sm:grid sm:grid-cols-[7rem_1fr_auto_auto_auto] sm:gap-x-4">
            <span className="font-mono uppercase tracking-wider">Factura</span>
            <span className="hidden font-mono uppercase tracking-wider sm:block">Vence</span>
            <span className="hidden text-right font-mono uppercase tracking-wider sm:block">Total</span>
            <span className="hidden text-right font-mono uppercase tracking-wider sm:block">Abonado</span>
            <span className="text-right font-mono uppercase tracking-wider">Saldo</span>
          </div>
          <ul className="mt-2 divide-y divide-dashed divide-espresso-700/70">
            {c.detalle.map((f) => (
              <li
                key={f.numero}
                className="flex items-baseline justify-between gap-3 py-2 text-sm sm:grid sm:grid-cols-[7rem_1fr_auto_auto_auto] sm:items-center sm:gap-x-4"
              >
                <span className="font-mono text-sand-200">{f.numero}</span>
                <span className="text-[11px] text-sand-500 sm:text-xs">
                  {f.fecha}
                  <span className={f.dias > 90 ? "text-[#c2415a]" : f.dias < 0 ? "text-matched" : "text-sand-500"}>
                    {f.dias < 0 ? ` · faltan ${-f.dias} d` : ` · ${f.dias} d`}
                  </span>
                </span>
                <span className="hidden text-right font-mono text-xs tabular-nums text-sand-400 sm:block">
                  {cop.format(f.total)}
                </span>
                <span className="hidden text-right font-mono text-xs tabular-nums text-sand-400 sm:block">
                  {f.abonado ? cop.format(f.abonado) : "—"}
                </span>
                <span className="text-right font-mono text-sm tabular-nums text-sand-100">
                  {cop.format(f.saldo)}
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center justify-between border-t border-dashed border-espresso-600 pt-3">
            <span className="font-mono text-[11px] uppercase tracking-wider text-sand-500">
              Total {c.cliente}
            </span>
            <span className="font-mono text-sm font-semibold tabular-nums text-amber">
              {cop.format(c.saldo)}
            </span>
          </div>
        </div>
      )}
    </li>
  );
}
