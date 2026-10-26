import { useEffect, useMemo, useState } from "react";
import { api, type EstadoExistencia, type ExistenciasResult, type FilaExistencia } from "../api";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});
const num = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 1 });

const PERIODOS = [7, 15, 30];
const COBERTURAS = [3, 7, 15];

type Filtro = "pedir" | "alerta" | "todo";
const FILTROS: { id: Filtro; etiqueta: string }[] = [
  { id: "pedir", etiqueta: "Por pedir" },
  { id: "alerta", etiqueta: "Agotados y bajos" },
  { id: "todo", etiqueta: "Todo" },
];

const ESTADO: Record<EstadoExistencia, { texto: string; clase: string }> = {
  agotado: { texto: "Agotado", clase: "border-pending/50 bg-pending/15 text-pending" },
  bajo: { texto: "Bajo mínimo", clase: "border-amber/50 bg-amber/10 text-amber" },
  alcanza_poco: { texto: "Alcanza poco", clase: "border-amber/30 bg-amber/5 text-amber-bright" },
  ok: { texto: "OK", clase: "border-matched/40 bg-matched/10 text-matched" },
  sin_movimiento: { texto: "Sin movimiento", clase: "border-espresso-600 text-sand-500" },
};

/** "+3", "-2", "0" — los movimientos se leen mejor con signo. */
function conSigno(v: number): string {
  if (!v) return "0";
  return `${v > 0 ? "+" : "−"}${num.format(Math.abs(v))}`;
}

/**
 * Existencias y pedido: por producto o ingrediente, el stock al inicio del
 * periodo, lo que entró, lo que se consumió y el actual, con una cantidad
 * sugerida para pedir agrupada por el proveedor de la última compra.
 *
 * El cálculo vive en informe_stock.py (el mismo de la consola y el CSV). Aquí
 * solo se filtra, se ajusta la cantidad a pedir y se copia el pedido.
 */
export default function StockView() {
  const [dias, setDias] = useState(15);
  const [cobertura, setCobertura] = useState(7);
  const [data, setData] = useState<ExistenciasResult | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filtro, setFiltro] = useState<Filtro>("pedir");
  const [buscar, setBuscar] = useState("");
  // Cantidades editadas a mano; lo que no esté aquí usa el sugerido.
  const [pedido, setPedido] = useState<Record<string, number>>({});
  const [copiado, setCopiado] = useState<string | null>(null);

  useEffect(() => {
    setCargando(true);
    setError(null);
    api
      .existencias({ dias, cobertura })
      .then((d) => {
        setData(d);
        setPedido({});
      })
      .catch((e) => setError(String(e)))
      .finally(() => setCargando(false));
  }, [dias, cobertura]);

  const cantidad = (f: FilaExistencia) => pedido[f.id] ?? f.pedir;

  const grupos = useMemo(() => {
    if (!data) return [];
    const q = buscar.trim().toLowerCase();
    const visibles = data.filas.filter((f) => {
      if (q && !`${f.nombre} ${f.proveedor} ${f.categoria}`.toLowerCase().includes(q)) return false;
      // Una fila que se editó se queda visible aunque se ponga en 0 mientras se escribe.
      if (filtro === "pedir") return f.pedir > 0 || f.id in pedido;
      if (filtro === "alerta") return f.estado !== "ok" && f.estado !== "sin_movimiento";
      return true;
    });
    const porProveedor = new Map<string, FilaExistencia[]>();
    for (const f of visibles) {
      porProveedor.set(f.proveedor, [...(porProveedor.get(f.proveedor) ?? []), f]);
    }
    return [...porProveedor.entries()];
  }, [data, filtro, buscar, pedido]);

  const totalPedido = useMemo(
    () => (data?.filas ?? []).reduce((s, f) => s + cantidad(f) * f.costo_unitario, 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, pedido]
  );

  async function copiar(proveedor: string, filas: FilaExistencia[]) {
    const lineas = filas
      .filter((f) => cantidad(f) > 0)
      .map((f) => `- ${num.format(cantidad(f))} ${f.unidad === "und" ? "" : f.unidad + " "}${f.nombre}`);
    if (!lineas.length) return;
    const hoy = new Date().toLocaleDateString("es-CO", { day: "numeric", month: "short" });
    const texto = `Pedido ${hoy}${proveedor.startsWith("Sin ") ? "" : ` · ${proveedor}`}\n${lineas.join("\n")}`;
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(proveedor);
      setTimeout(() => setCopiado((c) => (c === proveedor ? null : c)), 2000);
    } catch {
      window.prompt("Copia el pedido:", texto);
    }
  }

  function descargarCsv() {
    if (!data) return;
    const cols: (keyof FilaExistencia)[] = [
      "proveedor", "categoria", "nombre", "unidad", "inicial", "compras", "consumo", "ajustes",
      "actual", "minimo", "consumo_diario", "dias_alcanza", "pedir", "costo_unitario", "estado",
    ];
    const filas = grupos.flatMap(([, fs]) => fs);
    const csv = [
      cols.join(";"),
      ...filas.map((f) =>
        cols
          .map((c) => {
            const v = c === "pedir" ? cantidad(f) : f[c];
            return typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : String(v ?? "");
          })
          .join(";")
      ),
    ].join("\n");
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `existencias_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (cargando && !data) {
    return (
      <p className="py-16 text-center text-sm text-sand-500">
        Leyendo el kardex de Loggro… (puede tardar unos segundos)
      </p>
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

  const r = data.resumen;

  return (
    <div className={`grid gap-6 transition-opacity ${cargando ? "opacity-60" : ""}`}>
      {/* Resumen y parámetros */}
      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-6 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-amber">
              Pedido sugerido
            </p>
            <p className="mt-2 font-display text-4xl font-bold text-sand-50">{cop.format(totalPedido)}</p>
            <p className="mt-1 text-xs text-sand-500">
              {r.por_pedir} ítems por pedir · consumo de los últimos {data.dias} días · para que alcance{" "}
              {data.cobertura} días
            </p>
          </div>
          <div className="grid gap-2 text-xs">
            <Selector etiqueta="Consumo de" valores={PERIODOS} actual={dias} onChange={setDias} sufijo="d" />
            <Selector
              etiqueta="Que alcance"
              valores={COBERTURAS}
              actual={cobertura}
              onChange={setCobertura}
              sufijo="d"
            />
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Dato etiqueta="Ítems con inventario" valor={r.items} color="text-sand-50" />
          <Dato etiqueta="Agotados" valor={r.agotados} color="text-pending" />
          <Dato etiqueta="Bajos" valor={r.bajos} color="text-amber" />
          <Dato
            etiqueta="Stock negativo"
            valor={r.negativos}
            color="text-sand-300"
            sub={r.negativos ? "hacer conteo físico" : undefined}
          />
        </div>
      </section>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5 text-xs">
          {FILTROS.map((f) => (
            <button
              key={f.id}
              onClick={() => setFiltro(f.id)}
              className={`rounded-md px-3 py-1 font-medium transition ${
                filtro === f.id ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
              }`}
            >
              {f.etiqueta}
            </button>
          ))}
        </div>
        <input
          value={buscar}
          onChange={(e) => setBuscar(e.target.value)}
          placeholder="Buscar producto o proveedor…"
          className="min-w-0 flex-1 rounded-lg border border-espresso-600 bg-espresso-950/60 px-3 py-1.5 text-sm text-sand-100 placeholder:text-sand-500/60 focus:border-amber focus:outline-none"
        />
        <button
          onClick={descargarCsv}
          className="rounded-lg border border-espresso-600 px-3 py-1.5 text-xs font-medium text-sand-300 transition hover:border-amber hover:text-amber"
        >
          Descargar CSV
        </button>
      </div>

      {grupos.length === 0 && (
        <p className="py-10 text-center text-sm text-sand-500">Nada que mostrar con este filtro.</p>
      )}

      {/* Un bloque por proveedor */}
      {grupos.map(([proveedor, filas], gi) => {
        const subtotal = filas.reduce((s, f) => s + cantidad(f) * f.costo_unitario, 0);
        const conPedido = filas.some((f) => cantidad(f) > 0);
        return (
          <section
            key={proveedor}
            className="animate-rise overflow-hidden rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel"
            style={{ animationDelay: `${Math.min(gi, 8) * 50}ms` }}
          >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-espresso-700 px-5 py-3">
              <div>
                <h2 className="font-display text-lg font-semibold text-sand-50">{proveedor}</h2>
                <p className="text-xs text-sand-500">
                  {filas.length} ítems{subtotal > 0 && ` · ${cop.format(subtotal)} estimado`}
                </p>
              </div>
              {conPedido && (
                <button
                  onClick={() => copiar(proveedor, filas)}
                  className="rounded-lg bg-amber px-3 py-1.5 text-xs font-semibold text-espresso-950 transition hover:bg-amber-bright"
                >
                  {copiado === proveedor ? "¡Copiado!" : "Copiar pedido"}
                </button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead>
                  <tr className="text-right font-mono text-[10px] uppercase tracking-wider text-sand-500">
                    <th className="px-5 py-2 text-left font-medium">Producto</th>
                    <th className="px-2 py-2 font-medium" title="Stock al inicio del periodo">Inicial</th>
                    <th className="px-2 py-2 font-medium">Compras</th>
                    <th className="px-2 py-2 font-medium" title="Ventas, pedidos internos y cortesías">Consumo</th>
                    <th className="px-2 py-2 font-medium" title="Ajustes e inventario a cero">Ajustes</th>
                    <th className="px-2 py-2 font-medium">Actual</th>
                    <th className="px-2 py-2 font-medium">Mín.</th>
                    <th className="px-2 py-2 font-medium" title="Días que alcanza al ritmo de consumo">Alcanza</th>
                    <th className="px-5 py-2 font-medium">Pedir</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map((f) => (
                    <Fila
                      key={f.id}
                      f={f}
                      cantidad={cantidad(f)}
                      onCantidad={(v) => setPedido((p) => ({ ...p, [f.id]: v }))}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      <p className="text-center text-[11px] leading-relaxed text-sand-500/70">
        Inicial = stock al empezar el periodo, reconstruido con el kardex de Loggro (cada venta,
        compra y ajuste). Pedir = lo que falta para llegar al mínimo de Loggro o a {data.cobertura}{" "}
        días de consumo, lo que sea mayor. El proveedor es el de la última compra registrada.
        <br />
        Un stock negativo significa que se vendió más de lo que había cargado: conviene un conteo
        físico en la pestaña Inventario.
      </p>
    </div>
  );
}

function Fila({
  f,
  cantidad,
  onCantidad,
}: {
  f: FilaExistencia;
  cantidad: number;
  onCantidad: (v: number) => void;
}) {
  const est = ESTADO[f.estado];
  return (
    <tr className="border-t border-dashed border-espresso-700 text-right tabular-nums text-sand-300">
      <td className="px-5 py-2 text-left">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sand-100">{f.nombre}</span>
          <span className={`rounded-full border px-1.5 py-px text-[10px] font-medium ${est.clase}`}>
            {est.texto}
          </span>
        </div>
        <p className="text-[11px] text-sand-500">
          {f.categoria}
          {f.unidad !== "und" && ` · en ${f.unidad}`}
          {f.ultima_compra && ` · última compra ${f.ultima_compra}`}
        </p>
      </td>
      <td className="px-2 py-2">{num.format(f.inicial)}</td>
      <td className="px-2 py-2 text-matched/90">{f.compras ? conSigno(f.compras) : "—"}</td>
      <td className="px-2 py-2">{f.consumo ? `−${num.format(f.consumo)}` : "—"}</td>
      <td className="px-2 py-2 text-sand-500">{f.ajustes ? conSigno(f.ajustes) : "—"}</td>
      <td className={`px-2 py-2 font-semibold ${f.actual < 0 ? "text-pending" : "text-sand-50"}`}>
        {num.format(f.actual)}
      </td>
      <td className="px-2 py-2 text-sand-500">{f.minimo ? num.format(f.minimo) : "—"}</td>
      <td className="px-2 py-2 text-sand-500">
        {f.dias_alcanza != null ? `${num.format(f.dias_alcanza)} d` : "—"}
      </td>
      <td className="px-5 py-2">
        <input
          type="number"
          min={0}
          inputMode="decimal"
          value={cantidad}
          onChange={(e) => onCantidad(Math.max(0, Number(e.target.value) || 0))}
          className={`w-20 rounded-md border bg-espresso-950/60 px-2 py-1 text-right text-sm focus:border-amber focus:outline-none ${
            cantidad > 0 ? "border-amber/60 text-amber-bright" : "border-espresso-600 text-sand-500"
          }`}
        />
      </td>
    </tr>
  );
}

function Selector({
  etiqueta,
  valores,
  actual,
  onChange,
  sufijo,
}: {
  etiqueta: string;
  valores: number[];
  actual: number;
  onChange: (v: number) => void;
  sufijo: string;
}) {
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="text-sand-500">{etiqueta}</span>
      <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5">
        {valores.map((v) => (
          <button
            key={v}
            onClick={() => onChange(v)}
            className={`rounded-md px-2.5 py-1 font-medium transition ${
              actual === v ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
            }`}
          >
            {v}
            {sufijo}
          </button>
        ))}
      </div>
    </div>
  );
}

function Dato({
  etiqueta,
  valor,
  color,
  sub,
}: {
  etiqueta: string;
  valor: number;
  color: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-espresso-700 bg-espresso-950/40 px-3 py-2.5">
      <p className="font-mono text-[10px] uppercase tracking-wider text-sand-500">{etiqueta}</p>
      <p className={`mt-1 font-display text-lg font-bold ${color}`}>{valor.toLocaleString("es-CO")}</p>
      {sub && <p className="text-[10px] text-sand-500/70">{sub}</p>}
    </div>
  );
}
