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

const NEGOCIO = "Virus Pub";

/** Cuántas facturas se listan en el mensaje antes de resumir el resto. */
const FACTURAS_EN_MENSAJE = 5;

/**
 * Número en el formato que espera wa.me: solo dígitos, con indicativo de país.
 * Loggro guarda los celulares colombianos a 10 dígitos (3XX…), sin indicativo.
 * Devuelve "" si lo que hay no alcanza a ser un número marcable.
 */
function aWhatsapp(telefono: string): string {
  const d = (telefono || "").replace(/\D/g, "");
  if (!d) return "";
  if (d.length === 10 && d.startsWith("3")) return `57${d}`; // celular CO sin indicativo
  if (d.length >= 11 && d.length <= 15) return d; // ya trae indicativo
  return "";
}

/**
 * Mensaje de cobro. Cordial y concreto: saldo, corte y las facturas más
 * antiguas. Se limita el detalle porque hay clientes con más de 100 cuentas
 * abiertas y WhatsApp cortaría el mensaje.
 */
function mensajeCobro(c: CreditoCliente, generado: string): string {
  const vencidas = [...c.detalle].sort((a, b) => b.dias - a.dias);
  const listadas = vencidas.slice(0, FACTURAS_EN_MENSAJE);
  const resto = vencidas.length - listadas.length;

  const lineas = listadas.map((f) => {
    const cuando = f.dias < 0 ? `vence el ${fechaLarga(f.fecha)}` : `del ${fechaLarga(f.fecha)}`;
    return `• ${cop.format(f.saldo)} — cuenta ${f.numero} (${cuando})`;
  });
  if (resto > 0) lineas.push(`• y ${resto} ${resto === 1 ? "cuenta más" : "cuentas más"}`);

  const saludo = `¡Hola ${c.cliente.split(" ")[0]}! 👋`;
  const cierre =
    c.dias_mas_vieja < 0
      ? "Cuando quieras pasar a ponerte al día, con gusto te esperamos."
      : "Cuando puedas pasar a ponerte al día te lo agradecemos muchísimo.";

  return [
    saludo,
    "",
    `Te escribimos de ${NEGOCIO} para contarte cómo va tu cuenta, con corte al ${fechaLarga(generado)}:`,
    "",
    `Total pendiente: ${cop.format(c.saldo)} en ${c.facturas} ${c.facturas === 1 ? "cuenta" : "cuentas"}.`,
    "",
    ...lineas,
    "",
    cierre,
    "Si ya hiciste el pago, no tengas en cuenta este mensaje.",
    "",
    `¡Gracias por acompañarnos! 🍻`,
  ].join("\n");
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
  const [cobro, setCobro] = useState<CreditoCliente | null>(null);

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
              onCobrar={() => setCobro(c)}
            />
          ))}
        </ul>
      )}

      <p className="text-center font-mono text-[11px] uppercase tracking-[0.25em] text-sand-500/60">
        {clientes.length} de {data.clientes} clientes
      </p>

      {cobro && (
        <ModalCobro cliente={cobro} generado={data.generado} onCerrar={() => setCobro(null)} />
      )}
    </div>
  );
}

/**
 * Previsualización del cobro antes de abrir WhatsApp. El mensaje es editable y
 * el teléfono también: la mayoría de los clientes en Loggro no lo tiene
 * registrado, así que se puede escribir aquí sin salir de la vista.
 *
 * wa.me solo ABRE la conversación con el texto puesto; el envío final siempre
 * lo confirma la persona en WhatsApp.
 */
function ModalCobro({
  cliente: c,
  generado,
  onCerrar,
}: {
  cliente: CreditoCliente;
  generado: string;
  onCerrar: () => void;
}) {
  const [texto, setTexto] = useState(() => mensajeCobro(c, generado));
  const [telefono, setTelefono] = useState(c.telefono || "");
  const numero = aWhatsapp(telefono);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onCerrar();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onCerrar]);

  const abrirWhatsapp = () => {
    if (!numero) return;
    window.open(`https://wa.me/${numero}?text=${encodeURIComponent(texto)}`, "_blank", "noopener");
    onCerrar();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-espresso-950/80 p-4 backdrop-blur-sm sm:items-center"
      onClick={onCerrar}
      role="dialog"
      aria-modal="true"
      aria-label={`Cobrar por WhatsApp a ${c.cliente}`}
    >
      <div
        className="animate-rise max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-espresso-700 bg-espresso-900 p-6 shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.3em] text-amber">
              Cobrar por WhatsApp
            </p>
            <h3 className="mt-2 font-display text-xl font-bold text-sand-50">{c.cliente}</h3>
            <p className="mt-1 text-xs text-sand-500">
              {cop.format(c.saldo)} en {c.facturas} {c.facturas === 1 ? "cuenta" : "cuentas"} · corte
              al {fechaLarga(generado)}
            </p>
          </div>
          <button
            onClick={onCerrar}
            aria-label="Cerrar"
            className="shrink-0 rounded-lg p-1.5 text-sand-500 transition hover:bg-espresso-850 hover:text-sand-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <label className="mt-5 block">
          <span className="font-mono text-[11px] uppercase tracking-wider text-sand-500">
            Celular
          </span>
          <input
            value={telefono}
            onChange={(e) => setTelefono(e.target.value)}
            inputMode="tel"
            placeholder="300 123 4567"
            className="mt-1.5 w-full rounded-xl border border-espresso-600 bg-espresso-950/70 px-3 py-2.5 text-sm text-sand-50 outline-none transition placeholder:text-sand-500/60 focus:border-amber focus:shadow-glow"
          />
          {telefono.trim() && !numero ? (
            <span className="mt-1.5 block text-[11px] text-pending">
              Ese número no parece marcable. Usa 10 dígitos (300…) o incluye el indicativo del país.
            </span>
          ) : !c.telefono ? (
            <span className="mt-1.5 block text-[11px] text-sand-500">
              Este cliente no tiene celular en Loggro. Escríbelo aquí para enviarle el mensaje.
            </span>
          ) : null}
        </label>

        <label className="mt-4 block">
          <span className="font-mono text-[11px] uppercase tracking-wider text-sand-500">
            Mensaje
          </span>
          <textarea
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            rows={13}
            className="mt-1.5 w-full resize-y rounded-xl border border-espresso-600 bg-espresso-950/70 px-3 py-2.5 text-sm leading-relaxed text-sand-100 outline-none transition focus:border-amber focus:shadow-glow"
          />
        </label>

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            onClick={onCerrar}
            className="rounded-xl border border-espresso-600 px-4 py-2.5 text-sm font-semibold text-sand-400 transition hover:border-sand-500 hover:text-sand-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
          >
            Cancelar
          </button>
          <button
            onClick={abrirWhatsapp}
            disabled={!numero}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#25d366] px-4 py-2.5 text-sm font-bold text-espresso-950 transition hover:brightness-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber disabled:cursor-not-allowed disabled:opacity-40"
          >
            <IconoWhatsapp />
            Abrir WhatsApp
          </button>
        </div>
        <p className="mt-3 text-center text-[11px] text-sand-500">
          Se abre la conversación con el mensaje escrito. Tú decides cuándo enviarlo.
        </p>
      </div>
    </div>
  );
}

function IconoWhatsapp({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12.04 2c-5.46 0-9.91 4.45-9.91 9.91 0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38a9.87 9.87 0 0 0 4.74 1.21h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2Zm0 18.15h-.01a8.2 8.2 0 0 1-4.19-1.15l-.3-.18-3.12.82.83-3.04-.2-.31a8.19 8.19 0 0 1-1.26-4.38c0-4.54 3.7-8.23 8.25-8.23 2.2 0 4.27.86 5.83 2.42a8.18 8.18 0 0 1 2.41 5.82c0 4.54-3.7 8.23-8.24 8.23Zm4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.13-.16.24-.64.8-.79.97-.14.16-.29.18-.54.06-.25-.12-1.05-.39-1.99-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.01-.38.11-.5.11-.11.25-.29.37-.43.13-.15.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.4-.42-.56-.43h-.47c-.17 0-.43.06-.66.31-.23.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.12.17 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.67-1.18.21-.58.21-1.08.15-1.18-.06-.11-.23-.17-.48-.29Z" />
    </svg>
  );
}

function FilaCliente({
  cliente: c,
  indice,
  proporcion,
  abierto,
  onToggle,
  onCobrar,
}: {
  cliente: CreditoCliente;
  indice: number;
  proporcion: number;
  abierto: boolean;
  onToggle: () => void;
  onCobrar: () => void;
}) {
  const est = estado(c.dias_mas_vieja);
  return (
    <li
      className="animate-fade border-b border-dashed border-espresso-700 last:border-b-0"
      style={{ animationDelay: `${Math.min(indice, 12) * 35}ms` }}
    >
      {/* El cobro va fuera del botón que despliega la fila: un botón no puede
          anidar otro, y el tap en "cobrar" no debe abrir el detalle. */}
      <div className="flex items-stretch">
      <button
        onClick={onToggle}
        aria-expanded={abierto}
        className="group min-w-0 flex-1 px-5 py-4 text-left transition hover:bg-espresso-850/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber"
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

        <button
          onClick={onCobrar}
          title={`Cobrar por WhatsApp a ${c.cliente}`}
          aria-label={`Cobrar por WhatsApp a ${c.cliente}`}
          className="shrink-0 self-center mr-4 ml-1 rounded-xl border border-espresso-600 p-2.5 text-[#25d366] transition hover:border-[#25d366] hover:bg-[#25d366]/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
        >
          <IconoWhatsapp className="h-5 w-5" />
        </button>
      </div>

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
