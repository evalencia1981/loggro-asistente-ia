import { useEffect, useMemo, useState } from "react";
import { api, type InformePrecios, type Modulo, type ProductoPrecio } from "../api";
import CarteraView from "./CarteraView";
import UtilidadView from "./UtilidadView";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const pesos = (v: number | null) => (v == null ? "—" : cop.format(v));

/**
 * Informes. Cada uno es una entrada de INFORMES con el módulo (permiso) que lo
 * habilita: para sumar uno nuevo basta con agregarlo aquí y en acceso.MODULOS.
 */
const INFORMES = [
  {
    modulo: "utilidad",
    titulo: "Utilidad",
    descripcion: "Ventas contra compras y gastos, mes a mes.",
    Vista: UtilidadView,
  },
  {
    modulo: "cartera",
    titulo: "Cartera",
    descripcion: "Lo que deben los clientes por ventas a crédito.",
    Vista: CarteraView,
  },
  {
    modulo: "precios",
    titulo: "Precios y costos",
    descripcion: "Precio de venta, costo y margen de cada producto de la carta.",
    Vista: PreciosCostos,
  },
] as const;

/** Módulos que se muestran dentro de la pestaña Informes. */
export const MODULOS_INFORME = INFORMES.map((i) => i.modulo);

type ModuloInforme = (typeof INFORMES)[number]["modulo"];

export default function InformesView({ modulos }: { modulos: Modulo[] }) {
  const visibles = INFORMES.filter((i) => (modulos as string[]).includes(i.modulo));
  const [activo, setActivo] = useState<ModuloInforme | undefined>(visibles[0]?.modulo);
  const informe = visibles.find((i) => i.modulo === activo) ?? visibles[0];
  if (!informe) return null;
  const Vista = informe.Vista;

  return (
    <div className="grid gap-6">
      {visibles.length > 1 && (
        <nav className="flex flex-wrap justify-center gap-2" aria-label="Informes">
          {visibles.map((i) => (
            <button
              key={i.modulo}
              onClick={() => setActivo(i.modulo)}
              aria-pressed={i.modulo === informe.modulo}
              title={i.descripcion}
              className={`rounded-lg border px-3 py-1.5 text-sm font-semibold transition ${
                i.modulo === informe.modulo
                  ? "border-amber bg-amber/10 text-amber"
                  : "border-espresso-600 text-sand-400 hover:border-amber/60 hover:text-amber"
              }`}
            >
              {i.titulo}
            </button>
          ))}
        </nav>
      )}
      <Vista />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Precios y costos
// --------------------------------------------------------------------------- //
type Filtro = "todos" | "revisar" | "error";

const FILTROS: { id: Filtro; etiqueta: string }[] = [
  { id: "todos", etiqueta: "Todos" },
  { id: "revisar", etiqueta: "Para revisar" },
  { id: "error", etiqueta: "Costo erróneo" },
];

/**
 * Se consulta en vivo a Loggro (productos + ingredientes). El cálculo vive en
 * informe_precios.py, el mismo de la consola y el CSV.
 */
function PreciosCostos() {
  const [data, setData] = useState<InformePrecios | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todos");
  const [recarga, setRecarga] = useState(0);

  useEffect(() => {
    setCargando(true);
    setError(null);
    api
      .informePrecios()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setCargando(false));
  }, [recarga]);

  const grupos = useMemo(() => {
    const t = q.trim().toLowerCase();
    const filas = (data?.productos ?? []).filter(
      (p) =>
        (filtro === "todos" ||
          (filtro === "revisar" && p.estado !== "ok") ||
          (filtro === "error" && p.estado === "error")) &&
        (!t || p.producto.toLowerCase().includes(t) || p.categoria.toLowerCase().includes(t))
    );
    const m = new Map<string, ProductoPrecio[]>();
    for (const p of filas) m.set(p.categoria, [...(m.get(p.categoria) ?? []), p]);
    return { filas: filas.length, lista: [...m.entries()] };
  }, [data, q, filtro]);

  if (cargando && !data) {
    return <p className="py-16 text-center text-sm text-sand-500">Consultando productos en Loggro…</p>;
  }
  if (error && !data) {
    return (
      <p className="rounded-xl border border-pending/40 bg-pending/10 px-4 py-3 text-sm text-pending">
        {error}
      </p>
    );
  }
  if (!data) return null;

  const r = data.resumen;

  return (
    <div className="grid gap-6">
      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-6 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-amber">
              Precios y costos
            </p>
            <p className="mt-2 max-w-xl text-sm text-sand-400">
              Precio de venta, costo, utilidad y margen de cada producto activo. Consultado{" "}
              {new Date(data.generado).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" })}.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => descargarCsv(data.productos)}
              className="rounded-lg border border-espresso-600 px-3 py-1.5 text-xs font-semibold text-sand-300 transition hover:border-amber hover:text-amber"
            >
              Descargar CSV
            </button>
            <button
              onClick={() => setRecarga((n) => n + 1)}
              disabled={cargando}
              className="rounded-lg border border-espresso-600 px-3 py-1.5 text-xs font-semibold text-sand-300 transition hover:border-amber hover:text-amber disabled:opacity-50"
            >
              {cargando ? "Actualizando…" : "Actualizar"}
            </button>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Dato etiqueta="Productos" valor={String(r.productos)} color="text-sand-50" />
          <Dato
            etiqueta="Con costo"
            valor={String(r.con_costo)}
            color="text-sand-300"
            sub={`${r.sin_costo} sin costo`}
          />
          <Dato
            etiqueta="Margen típico"
            valor={`${Math.round(r.margen_mediano)}%`}
            color="text-matched"
            sub="mediana"
          />
          <Dato
            etiqueta="Costo erróneo"
            valor={String(r.errores)}
            color={r.errores ? "text-pending" : "text-sand-300"}
            sub={`${r.revisar} para revisar`}
          />
        </div>
        {error && <p className="mt-3 text-xs text-pending">No se pudo actualizar: {error}</p>}
      </section>

      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel [animation-delay:80ms]">
        <div className="flex flex-wrap items-center gap-3 border-b border-espresso-700 px-5 py-4">
          <input
            id="buscar-precio"
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar producto o categoría"
            aria-label="Buscar producto o categoría"
            className="min-w-0 flex-1 basis-56 rounded-lg border border-espresso-600 bg-espresso-950/50 px-3 py-1.5 text-sm text-sand-100 placeholder:text-sand-500 focus:border-amber focus:outline-none"
          />
          <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5 text-xs">
            {FILTROS.map((f) => (
              <button
                key={f.id}
                onClick={() => setFiltro(f.id)}
                aria-pressed={filtro === f.id}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  filtro === f.id ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
                }`}
              >
                {f.etiqueta}
              </button>
            ))}
          </div>
          <span className="font-mono text-[11px] text-sand-500">
            {grupos.filas} de {data.productos.length}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-sm">
            <thead>
              <tr className="text-left font-mono text-[10px] uppercase tracking-wider text-sand-500">
                <th className="px-5 py-2 font-medium">Producto</th>
                <th className="px-3 py-2 text-right font-medium">Precio</th>
                <th className="px-3 py-2 text-right font-medium">Costo</th>
                <th className="px-3 py-2 text-right font-medium">Utilidad</th>
                <th className="px-3 py-2 text-right font-medium">Margen</th>
                <th className="px-5 py-2 font-medium">Notas</th>
              </tr>
            </thead>
            <tbody>
              {grupos.lista.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-sand-500">
                    Ningún producto coincide con la búsqueda.
                  </td>
                </tr>
              )}
              {grupos.lista.map(([cat, ps]) => (
                <Grupo key={cat} categoria={cat} productos={ps} margenBajo={data.margen_bajo} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-center text-[11px] leading-relaxed text-sand-500/70">
        Costo: promedio de Loggro, o el último precio de compra si el promedio está en 0. Recetas:
        suma de cada ingrediente por la cantidad que lleva.
        <br />
        Los combos no tienen costo porque depende de lo que elija el cliente. "Costo erróneo" = costo
        mayor que el precio o menor al 3% del precio.
      </p>
    </div>
  );
}

function Grupo({
  categoria,
  productos,
  margenBajo,
}: {
  categoria: string;
  productos: ProductoPrecio[];
  margenBajo: number;
}) {
  return (
    <>
      <tr className="bg-espresso-950/50">
        <td colSpan={6} className="px-5 pb-1.5 pt-3 font-display text-sm font-semibold text-sand-100">
          {categoria}
          <span className="ml-2 font-mono text-[10px] font-normal text-sand-500">{productos.length}</span>
        </td>
      </tr>
      {productos.map((p) => (
        <tr key={p.id} className="border-b border-dashed border-espresso-700 last:border-b-0">
          <td className="px-5 py-2 text-sand-100">{p.producto}</td>
          <td className="px-3 py-2 text-right font-mono tabular-nums text-sand-100">{pesos(p.precio)}</td>
          <td className="px-3 py-2 text-right font-mono tabular-nums text-sand-300">
            {pesos(p.costo)}
            {p.costo != null && (
              <span className="block text-[10px] text-sand-500">{p.fuente_costo}</span>
            )}
          </td>
          <td className="px-3 py-2 text-right font-mono tabular-nums text-sand-300">{pesos(p.utilidad)}</td>
          <td className="px-3 py-2 text-right">
            <Margen m={p.margen} bajo={margenBajo} />
          </td>
          <td
            className={`max-w-[18rem] px-5 py-2 text-xs ${
              p.estado === "error" ? "text-pending" : p.estado === "revisar" ? "text-amber" : "text-sand-500"
            }`}
          >
            {p.notas}
          </td>
        </tr>
      ))}
    </>
  );
}

function Margen({ m, bajo }: { m: number | null; bajo: number }) {
  if (m == null) return <span className="font-mono text-sand-500">—</span>;
  const cls =
    m < 0
      ? "bg-pending/15 text-pending"
      : m < bajo
        ? "bg-amber/15 text-amber"
        : "bg-matched/15 text-matched";
  return (
    <span className={`inline-block min-w-[3.5rem] rounded-full px-2 py-0.5 text-right font-mono text-xs ${cls}`}>
      {Math.round(m)}%
    </span>
  );
}

function Dato({
  etiqueta,
  valor,
  color,
  sub,
}: {
  etiqueta: string;
  valor: string;
  color: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-espresso-700 bg-espresso-950/40 px-3 py-2.5">
      <p className="font-mono text-[10px] uppercase tracking-wider text-sand-500">{etiqueta}</p>
      <p className={`mt-1 font-display text-lg font-bold ${color}`}>{valor}</p>
      {sub && <p className="text-[10px] text-sand-500/70">{sub}</p>}
    </div>
  );
}

/** CSV con ";" y BOM para que Excel en español lo abra con acentos y columnas. */
function descargarCsv(filas: ProductoPrecio[]) {
  const celda = (v: string | number | null) => {
    const s = v == null ? "" : String(v);
    return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const r = (v: number | null) => (v == null ? "" : Math.round(v));
  const lineas = [
    ["Categoría", "Producto", "Precio", "Costo", "Fuente costo", "Utilidad", "Margen %", "Notas"],
    ...filas.map((p) => [
      p.categoria,
      p.producto,
      r(p.precio),
      r(p.costo),
      p.fuente_costo,
      r(p.utilidad),
      p.margen == null ? "" : p.margen.toFixed(1).replace(".", ","),
      p.notas,
    ]),
  ].map((l) => l.map(celda).join(";"));
  const blob = new Blob(["﻿" + lineas.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `precios-y-costos-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
