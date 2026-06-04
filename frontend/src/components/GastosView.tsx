import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CrearGastoResult,
  type GastoExtractResult,
  type GastoChatResult,
  type GastoExtraccion,
  type Provider,
  type Responsable,
  type TipoGasto,
} from "../api";
import ImagenUpload from "./ImagenUpload";
import ChatCaptura from "./ChatCaptura";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

const hoyISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
};

// Convierte una fecha extraída (DD/MM/YYYY, ISO…) a YYYY-MM-DD para el input date.
function aISO(fecha?: string): string {
  const s = (fecha || "").trim();
  if (!s) return hoyISO();
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
  const m = s.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$/);
  if (m) {
    const [, d, mo, y] = m;
    const yyyy = y.length === 2 ? `20${y}` : y;
    return `${yyyy}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }
  return hoyISO();
}

export default function GastosView() {
  const [tipos, setTipos] = useState<TipoGasto[]>([]);
  const [responsables, setResponsables] = useState<Responsable[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [inputMode, setInputMode] = useState<"foto" | "chat">("foto");

  // Formulario del gasto
  const [fecha, setFecha] = useState(hoyISO());
  const [typeExpenseId, setTypeExpenseId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [paidToId, setPaidToId] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [formaPago, setFormaPago] = useState("");
  const [concepto, setConcepto] = useState("");
  const [subtotal, setSubtotal] = useState(0);
  const [impuestos, setImpuestos] = useState(0);
  const [saleDeCaja, setSaleDeCaja] = useState(false);

  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<CrearGastoResult | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nitSugerido, setNitSugerido] = useState<string | null>(null);

  useEffect(() => {
    api.gastosTipos().then(setTipos).catch((e) => setError(String(e)));
    api.gastosResponsables().then(setResponsables).catch(() => {});
    api.providers().then(setProviders).catch(() => {});
  }, []);

  const total = (subtotal || 0) + (impuestos || 0);

  const aplicarGasto = (r: GastoExtractResult | GastoChatResult) => {
    const g: GastoExtraccion = r.gasto;
    setConcepto(g.concepto || "");
    setSubtotal(g.subtotal || 0);
    setImpuestos(g.impuestos || 0);
    setInvoiceNumber(g.documento?.numero || "");
    setFormaPago(g.forma_pago || "");
    if (g.documento?.fecha) setFecha(aISO(g.documento.fecha));
    if (r.proveedor_sugerido) setProviderId(r.proveedor_sugerido.id);
    if (r.tipo_sugerido) setTypeExpenseId(r.tipo_sugerido);
    if (r.responsable_sugerido) setPaidToId(r.responsable_sugerido);
    setNitSugerido(g.proveedor?.nit || null);
    setResult(null);
    setDeleted(false);
    setError(null);
  };

  const guardar = async () => {
    setError(null);
    if (!typeExpenseId) return setError("Selecciona el tipo de gasto.");
    if (!concepto.trim()) return setError("El concepto del gasto es obligatorio.");
    setCreating(true);
    try {
      const r = await api.crearGasto({
        type_expense_id: typeExpenseId,
        paid_to_id: paidToId || undefined,
        provider_id: providerId || undefined,
        invoice_number: invoiceNumber,
        forma_pago: formaPago,
        concepto: concepto.trim(),
        subtotal: subtotal || 0,
        impuestos: impuestos || 0,
        sale_de_caja: saleDeCaja,
        fecha,
      });
      setResult(r);
      setDeleted(false);
    } catch (e) {
      setError(`No se pudo registrar el gasto: ${e}`);
    } finally {
      setCreating(false);
    }
  };

  const eliminar = async () => {
    if (!result?.expense_id) return;
    setError(null);
    setDeleting(true);
    try {
      await api.eliminarGasto(result.expense_id);
      setDeleted(true);
    } catch (e) {
      setError(`No se pudo deshacer el gasto: ${e}`);
    } finally {
      setDeleting(false);
    }
  };

  const proveedorNoRegistrado = nitSugerido && !providerId;

  const resumenChat = useMemo(
    () => (g: GastoExtraccion | null) =>
      g?.concepto ? `${g.concepto} · ${cop.format((g.subtotal || 0) + (g.impuestos || 0))}` : null,
    []
  );

  return (
    <div className="grid gap-6 lg:grid-cols-12">
      {/* Captura */}
      <section className="lg:col-span-5">
        <div className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-5 shadow-panel">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-display text-lg font-semibold text-sand-50">1 · Documento</h2>
            <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5 text-xs">
              <button
                onClick={() => setInputMode("foto")}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  inputMode === "foto" ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
                }`}
              >
                📷 Foto
              </button>
              <button
                onClick={() => setInputMode("chat")}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  inputMode === "chat" ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
                }`}
              >
                💬 Chat / Voz
              </button>
            </div>
          </div>
          <p className="mb-3 mt-1 text-xs text-sand-500">
            {inputMode === "foto"
              ? "Sube la foto del recibo y la IA llena el gasto."
              : "Dicta o escribe el gasto y la IA lo arma."}
          </p>

          {inputMode === "foto" ? (
            <ImagenUpload<GastoExtractResult>
              extraer={api.gastosExtraer}
              onResult={aplicarGasto}
              etiqueta="Toca para tomar/subir la foto del recibo"
            />
          ) : (
            <ChatCaptura<GastoExtraccion, GastoChatResult>
              placeholder="Ej. “arriendo del local 1.500.000, factura 123”"
              sugerencias={[
                "Arriendo del local 1.500.000",
                "Servicios públicos EPM 320.000",
                "factura 123, pago por transferencia",
              ]}
              resumen={resumenChat}
              enviar={async (mensaje, estado, historial) => {
                const r = await api.gastosChat({ mensaje, gasto: estado, historial });
                return { estado: r.gasto, respuesta: r.respuesta, result: r };
              }}
              onResult={aplicarGasto}
            />
          )}
        </div>
      </section>

      {/* Formulario del gasto */}
      <section className="lg:col-span-7">
        <div className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-5 shadow-panel [animation-delay:80ms]">
          <h2 className="font-display text-lg font-semibold text-sand-50">2 · Gasto</h2>
          <p className="mb-4 mt-1 text-xs text-sand-500">
            Revisa y completa. El tipo y el responsable los eliges tú.
          </p>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Fecha">
              <input
                type="date"
                value={fecha}
                onChange={(e) => setFecha(e.target.value)}
                className={inputCls}
              />
            </Field>

            <Field label="Tipo de gasto *">
              <select value={typeExpenseId} onChange={(e) => setTypeExpenseId(e.target.value)} className={inputCls}>
                <option value="">— Selecciona —</option>
                {tipos.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Proveedor" full>
              <select value={providerId} onChange={(e) => setProviderId(e.target.value)} className={inputCls}>
                <option value="">— (opcional) —</option>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.document ? `· ${p.document}` : ""}
                  </option>
                ))}
              </select>
              {proveedorNoRegistrado && (
                <p className="mt-1 text-[11px] text-pending">
                  Proveedor de la foto (NIT {nitSugerido}) no está registrado. Selecciónalo o déjalo vacío.
                </p>
              )}
            </Field>

            <Field label="N° Factura">
              <input value={invoiceNumber} onChange={(e) => setInvoiceNumber(e.target.value)} className={inputCls} />
            </Field>

            <Field label="Forma de Pago">
              <input
                value={formaPago}
                onChange={(e) => setFormaPago(e.target.value)}
                placeholder="efectivo, transferencia…"
                className={inputCls}
              />
            </Field>

            <Field label="Concepto del Gasto *" full>
              <input value={concepto} onChange={(e) => setConcepto(e.target.value)} className={inputCls} />
            </Field>

            <Field label="Subtotal *">
              <input
                type="number"
                value={subtotal}
                onChange={(e) => setSubtotal(Number(e.target.value) || 0)}
                className={inputCls}
              />
            </Field>

            <Field label="Impuestos">
              <input
                type="number"
                value={impuestos}
                onChange={(e) => setImpuestos(Number(e.target.value) || 0)}
                className={inputCls}
              />
            </Field>

            <Field label="Responsable">
              <select value={paidToId} onChange={(e) => setPaidToId(e.target.value)} className={inputCls}>
                <option value="">— (opcional) —</option>
                {responsables.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Total">
              <div className="flex h-[42px] items-center rounded-xl border border-espresso-600 bg-espresso-950/40 px-3 font-mono text-sm text-sand-50">
                {cop.format(total)}
              </div>
            </Field>

            <div className="col-span-2 flex items-center gap-3">
              <button
                onClick={() => setSaleDeCaja((v) => !v)}
                className={`relative h-6 w-11 shrink-0 rounded-full transition ${
                  saleDeCaja ? "bg-amber" : "bg-espresso-700"
                }`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-sand-50 transition ${
                    saleDeCaja ? "left-[22px]" : "left-0.5"
                  }`}
                />
              </button>
              <span className="text-sm text-sand-200">Sale de caja</span>
              <span className="text-xs text-sand-500">(descuenta de la caja abierta)</span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {result ? (
              <div className="flex w-full flex-col gap-2">
                <p className="font-display text-lg text-matched">
                  {deleted ? "Gasto deshecho en Loggro" : "Gasto registrado en Loggro ✦"}
                </p>
                <p className="text-xs text-sand-500">
                  {cop.format(result.total)}
                  {result.expense_id ? ` · gasto …${result.expense_id.slice(-6)}` : ""}
                </p>
                {!deleted && result.expense_id && (
                  <button
                    onClick={eliminar}
                    disabled={deleting}
                    className="mt-1 inline-flex w-fit items-center gap-2 rounded-xl border border-pending/50 bg-pending/10 px-4 py-2 text-sm font-semibold text-pending transition hover:bg-pending/20 disabled:opacity-60"
                  >
                    {deleting ? "Deshaciendo…" : "Deshacer (eliminar de Loggro)"}
                  </button>
                )}
              </div>
            ) : (
              <button
                onClick={guardar}
                disabled={creating}
                className="inline-flex items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
              >
                {creating ? "Guardando…" : "Guardar gasto en Loggro"}
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </button>
            )}
          </div>

          {error && (
            <p className="mt-4 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-sm text-pending">
              {error}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

const inputCls =
  "w-full appearance-none rounded-xl border border-espresso-600 bg-espresso-900/70 px-3 py-2.5 text-sm text-sand-50 outline-none transition focus:border-amber focus:shadow-glow";

function Field({ label, children, full }: { label: string; children: React.ReactNode; full?: boolean }) {
  return (
    <label className={`flex flex-col gap-1 ${full ? "col-span-2" : ""}`}>
      <span className="text-xs text-sand-400">{label}</span>
      {children}
    </label>
  );
}
