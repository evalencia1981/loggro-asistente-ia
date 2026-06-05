import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CacheStatus,
  type CheckResult,
  type ExtractResult,
  type MovimientoResult,
  type Provider,
  type Product,
  type TirillaItem,
} from "./api";
import ProductPicker from "./components/ProductPicker";
import TirillaUpload from "./components/TirillaUpload";
import ChatFactura from "./components/ChatFactura";
import GastosView from "./components/GastosView";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

// Tirilla de ejemplo (la "Donde el Calvo" del spec): "desc | cantidad | total"
const EJEMPLO = `POKER 330ML | 60 | 137400
AGUILA 330ML | 60 | 142560
RON BACARDI CART | 1 | 52788
STELLA ARTOIS 6PACK | 1 | 22977
HEINEKEN 330ML | 2 | 7938`;

function formatAge(secs: number | null): string {
  if (secs == null) return "sin sincronizar";
  if (secs < 5) return "recién sincronizado";
  if (secs < 60) return `hace ${secs}s`;
  if (secs < 3600) return `hace ${Math.floor(secs / 60)}m`;
  return `hace ${Math.floor(secs / 3600)}h`;
}

function parseTirilla(text: string): TirillaItem[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split("|").map((p) => p.trim());
      const num = (s?: string) => {
        if (!s) return null;
        const n = Number(s.replace(/[^\d.-]/g, ""));
        return Number.isFinite(n) ? n : null;
      };
      return { descripcion: parts[0], cantidad: num(parts[1]), total: num(parts[2]) };
    });
}

export default function App() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerId, setProviderId] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState<CheckResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [editing, setEditing] = useState<Set<string>>(new Set());
  const [cacheInfo, setCacheInfo] = useState<CacheStatus | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [meta, setMeta] = useState<{
    numero: string;
    total: number;
    cuadra: boolean;
    proveedorNombre: string;
    nit: string;
    matched: boolean;
    fecha: string;
    pagado: boolean;
  } | null>(null);
  const [creating, setCreating] = useState(false);
  const [movResult, setMovResult] = useState<MovimientoResult | null>(null);
  const [confirmCreate, setConfirmCreate] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [inputMode, setInputMode] = useState<"foto" | "chat">("foto");
  const [factores, setFactores] = useState<Record<string, number>>({});
  const [vista, setVista] = useState<"compras" | "gastos">("compras");

  useEffect(() => {
    api
      .health()
      .then((h) => setBackendOk(h.ok))
      .catch(() => setBackendOk(false));
    api
      .providers()
      .then(setProviders)
      .catch((e) => setError(String(e)));
    api.cacheStatus().then(setCacheInfo).catch(() => {});
  }, []);

  const sincronizar = async () => {
    setSyncing(true);
    setError(null);
    try {
      const info = await api.cacheRefresh();
      setCacheInfo(info);
      const provs = await api.providers(); // recargar el desplegable con lo nuevo
      setProviders(provs);
    } catch (e) {
      setError(`No se pudo sincronizar con Loggro: ${e}`);
    } finally {
      setSyncing(false);
    }
  };

  const provider = useMemo(
    () => providers.find((p) => p.id === providerId),
    [providers, providerId]
  );

  const runCheck = async (pid: string, items: TirillaItem[]) => {
    setError(null);
    if (!pid) return setError("Selecciona un proveedor.");
    if (items.length === 0) return setError("No hay ítems para analizar.");
    setAnalyzing(true);
    try {
      const r = await api.check(pid, items);
      setResult(r);
      setEditing(new Set());
      setMovResult(null);
      setConfirmCreate(false);
      setDeleted(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const analizar = () => runCheck(providerId, parseTirilla(text));

  const onExtracted = (r: ExtractResult) => {
    const ex = r.extraccion;
    // Volcar ítems al textarea: "descripción | cantidad | total"
    const lineas = ex.items
      .map((i) => `${i.descripcion} | ${i.cantidad ?? ""} | ${i.total ?? ""}`)
      .join("\n");
    setText(lineas);
    setMeta({
      numero: ex.documento?.numero || "",
      total: ex.totales?.total_pagar || 0,
      cuadra: !!ex.cuadra,
      proveedorNombre: ex.proveedor?.nombre_tirilla || "",
      nit: ex.proveedor?.nit || "",
      matched: !!r.proveedor_sugerido,
      fecha: ex.documento?.fecha || "",
      pagado: !!ex.documento?.pagado,
    });
    setResult(null);
    if (r.proveedor_sugerido) {
      const pid = r.proveedor_sugerido.id;
      setProviderId(pid);
      runCheck(pid, ex.items as TirillaItem[]); // proveedor reconocido → analizar ya
    } else {
      setProviderId("");
      setError(
        `Proveedor "${ex.proveedor?.nombre_tirilla}" (NIT ${ex.proveedor?.nit}) no está registrado. Selecciónalo o créalo en Loggro y sincroniza.`
      );
    }
  };

  const asignar = async (descripcion: string, p: Product, factor = 1) => {
    if (!result) return;
    setError(null);
    try {
      await api.assign({
        provider_id: result.provider_id,
        provider_name: provider?.name,
        descripcion,
        product_id: p.id,
        product_name: p.name,
        factor,
      });
    } catch (e) {
      // Sin esto el fallo era silencioso: el tap "no seleccionaba" nada.
      setError(`No se pudo guardar la homologación: ${String(e)}`);
      return;
    }
    setResult((prev) => {
      if (!prev) return prev;
      const items = prev.items.map((it) =>
        it.descripcion === descripcion
          ? { ...it, reconocido: true, product_id: p.id, product_name: p.name, factor }
          : it
      );
      const reconocidos = items.filter((i) => i.reconocido).length;
      return { ...prev, items, reconocidos, pendientes: items.length - reconocidos };
    });
    setEditing((s) => {
      const n = new Set(s);
      n.delete(descripcion);
      return n;
    });
  };

  const crearMovimiento = async () => {
    if (!result) return;
    setError(null);
    setCreating(true);
    try {
      const items = result.items.map((it) => ({
        descripcion: it.descripcion,
        product_id: (it.product_id ?? "") as string,
        cantidad: it.cantidad ?? 0,
        total: it.total ?? 0,
        factor: it.factor ?? 1,
      }));
      const r = await api.crearMovimiento({
        provider_id: result.provider_id,
        invoice_number: meta?.numero ?? "",
        fecha: meta?.fecha || null,
        pagado: meta?.pagado ?? false,
        nota: `Compra ${meta?.proveedorNombre || provider?.name || ""}`.trim(),
        items,
      });
      setMovResult(r);
      setConfirmCreate(false);
      setDeleted(false);
    } catch (e) {
      setError(`No se pudo registrar la compra en Loggro: ${e}`);
    } finally {
      setCreating(false);
    }
  };

  const eliminarMovimiento = async () => {
    if (!movResult?.movement_id) return;
    setError(null);
    setDeleting(true);
    try {
      await api.eliminarMovimiento(movResult.movement_id);
      setDeleted(true);
    } catch (e) {
      setError(`No se pudo deshacer la compra en Loggro: ${e}`);
    } finally {
      setDeleting(false);
    }
  };

  const totalCompra = result
    ? result.items.reduce((s, it) => s + (it.total ?? 0), 0)
    : 0;

  const pct = result && result.total ? Math.round((result.reconocidos / result.total) * 100) : 0;

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-5 py-8 md:px-8 md:py-12">
      {/* ---------- Header ---------- */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="animate-rise">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-amber text-espresso-950 shadow-glow">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M6 3h12l-1 8a5 5 0 0 1-10 0L6 3Z" />
                <path d="M7.5 9h9" />
                <path d="M9 21h6M12 16v5" />
              </svg>
            </span>
            <div>
              <p className="font-mono text-[11px] uppercase tracking-[0.35em] text-amber">
                Virus Pub
              </p>
              <h1 className="font-display text-3xl font-extrabold leading-none text-sand-50 md:text-4xl">
                Homologación
              </h1>
            </div>
          </div>
          <p className="mt-3 max-w-md text-sm text-sand-400">
            Empareja cada producto de la tirilla con su símil en Loggro.
            Lo que asignas se aprende por proveedor — no se vuelve a preguntar.
          </p>
        </div>

        <div className="flex items-center gap-3 animate-fade">
          <div className="flex flex-col items-end">
            <div className="flex items-center gap-2 rounded-full border border-espresso-700 bg-espresso-900/60 px-3 py-1.5 text-xs">
              <span
                className={`h-2 w-2 rounded-full ${
                  backendOk == null ? "bg-sand-500" : backendOk ? "bg-matched" : "bg-pending"
                }`}
              />
              <span className="text-sand-400">
                {backendOk == null ? "Conectando…" : backendOk ? "Loggro en línea" : "Sin conexión"}
              </span>
            </div>
            {cacheInfo && (
              <p className="mt-1.5 font-mono text-[10px] text-sand-500">
                {cacheInfo.products} prod · {cacheInfo.providers} prov ·{" "}
                {formatAge(cacheInfo.products_age)}
              </p>
            )}
          </div>

          <button
            onClick={sincronizar}
            disabled={syncing}
            title="Traer productos y proveedores nuevos desde Loggro"
            className="inline-flex items-center gap-2 rounded-full border border-espresso-600 bg-espresso-850 px-3.5 py-2 text-xs font-semibold text-sand-100 transition hover:border-amber hover:text-amber disabled:opacity-60"
          >
            <svg
              className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`}
              viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
            >
              <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
            </svg>
            {syncing ? "Sincronizando…" : "Sincronizar"}
          </button>
        </div>
      </header>

      <div className="mt-8 hairline h-px w-full" />

      {/* ---------- Navegación Compras / Gastos ---------- */}
      <div className="mt-6 flex justify-center">
        <div className="inline-flex rounded-xl border border-espresso-600 bg-espresso-950/50 p-1 text-sm">
          {(["compras", "gastos"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setVista(v)}
              className={`rounded-lg px-5 py-1.5 font-semibold capitalize transition ${
                vista === v ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      {vista === "gastos" ? (
        <div className="mt-8">
          <GastosView />
        </div>
      ) : (
      <>
      {/* ---------- Workspace ---------- */}
      <div className="mt-8 grid gap-6 lg:grid-cols-12">
        {/* Config */}
        <section className="lg:col-span-5">
          <div className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-5 shadow-panel [animation-delay:80ms]">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-display text-lg font-semibold text-sand-50">1 · Tirilla</h2>
              <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5 text-xs">
                <button
                  onClick={() => setInputMode("foto")}
                  className={`rounded-md px-3 py-1 font-medium transition ${
                    inputMode === "foto"
                      ? "bg-amber text-espresso-950"
                      : "text-sand-400 hover:text-amber"
                  }`}
                >
                  📷 Foto
                </button>
                <button
                  onClick={() => setInputMode("chat")}
                  className={`rounded-md px-3 py-1 font-medium transition ${
                    inputMode === "chat"
                      ? "bg-amber text-espresso-950"
                      : "text-sand-400 hover:text-amber"
                  }`}
                >
                  💬 Chat / Voz
                </button>
              </div>
            </div>
            <p className="mb-3 mt-1 text-xs text-sand-500">
              {inputMode === "foto"
                ? "Sube la foto y la IA lee proveedor, ítems y totales."
                : "Dicta o escribe la factura y la IA la arma conversando."}
            </p>
            {inputMode === "foto" ? (
              <TirillaUpload onExtracted={onExtracted} />
            ) : (
              <ChatFactura onResult={(r) => onExtracted(r)} />
            )}

            {meta && (
              <div className="mt-4 rounded-xl border border-espresso-600 bg-espresso-950/40 p-3 text-xs">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span className="text-sand-400">
                    Factura{" "}
                    <span className="font-mono text-sand-100">{meta.numero || "—"}</span>
                  </span>
                  <span className="text-sand-400">
                    Total{" "}
                    <span className="font-mono text-sand-100">{cop.format(meta.total)}</span>
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 font-medium ${
                      meta.cuadra ? "text-matched" : "text-pending"
                    }`}
                  >
                    {meta.cuadra ? "✓ cuadra" : "✗ no cuadra"}
                  </span>
                </div>
                <div className="mt-1.5 text-sand-500">
                  Proveedor:{" "}
                  <span className="text-sand-200">{meta.proveedorNombre || "—"}</span>
                  {meta.nit ? ` · NIT ${meta.nit}` : ""}{" "}
                  {meta.matched ? (
                    <span className="text-matched">· reconocido</span>
                  ) : (
                    <span className="text-pending">· sin registrar</span>
                  )}
                </div>
              </div>
            )}

            <div className="my-5 hairline h-px w-full" />

            <h2 className="font-display text-lg font-semibold text-sand-50">2 · Proveedor</h2>
            <p className="mb-3 mt-1 text-xs text-sand-500">
              Los nombres cambian según quién factura.
            </p>
            <div className="relative">
              <select
                value={providerId}
                onChange={(e) => setProviderId(e.target.value)}
                className="w-full appearance-none rounded-xl border border-espresso-600 bg-espresso-900/70 px-3 py-2.5 text-sm text-sand-50 outline-none transition focus:border-amber focus:shadow-glow"
              >
                <option value="">— Elegir proveedor —</option>
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} {p.document ? `· ${p.document}` : ""}
                  </option>
                ))}
              </select>
              <svg
                className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-sand-500"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </div>

            <h2 className="mt-6 font-display text-lg font-semibold text-sand-50">
              3 · Ítems de la tirilla
            </h2>
            <p className="mb-3 mt-1 text-xs text-sand-500">
              Se llenan solos al extraer. O edítalos:{" "}
              <code className="font-mono text-amber/90">descripción | cantidad | total</code>
            </p>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              placeholder={"POKER 330ML | 60 | 137400\nAGUILA 330ML | 60 | 142560\n…"}
              className="w-full resize-y rounded-xl border border-espresso-600 bg-espresso-950/60 p-3 font-mono text-[13px] leading-relaxed text-sand-100 outline-none transition placeholder:text-sand-500/50 focus:border-amber focus:shadow-glow"
            />

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                onClick={analizar}
                disabled={analyzing}
                className="group relative inline-flex items-center gap-2 overflow-hidden rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
              >
                {analyzing ? "Analizando…" : "Analizar tirilla"}
                <svg className="h-4 w-4 transition group-hover:translate-x-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </button>
              <button
                onClick={() => setText(EJEMPLO)}
                className="text-sm text-sand-400 underline-offset-4 transition hover:text-amber hover:underline"
              >
                Cargar ejemplo
              </button>
            </div>

            {error && (
              <p className="mt-4 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-sm text-pending">
                {error}
              </p>
            )}
          </div>
        </section>

        {/* Resultados — estilo tirilla */}
        <section className="lg:col-span-7">
          {!result ? (
            <EmptyState />
          ) : (
            <div className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel">
              {/* Progreso */}
              <div className="border-b border-dashed border-espresso-600 p-5">
                <div className="flex items-end justify-between">
                  <div>
                    <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-sand-500">
                      {provider?.name ?? "Proveedor"}
                    </p>
                    <p className="font-display text-2xl font-semibold text-sand-50">
                      {result.reconocidos}
                      <span className="text-sand-500"> / {result.total}</span>{" "}
                      <span className="text-base font-normal text-sand-400">reconocidos</span>
                    </p>
                  </div>
                  <span
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${
                      result.pendientes === 0
                        ? "bg-matched/15 text-matched"
                        : "bg-pending/15 text-pending"
                    }`}
                  >
                    {result.pendientes === 0 ? "Completo" : `${result.pendientes} pendientes`}
                  </span>
                </div>
                <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-espresso-700">
                  <div
                    className="h-full origin-left rounded-full bg-gradient-to-r from-amber-deep to-amber-bright animate-pour"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>

              {/* Lista de ítems */}
              <ul className="divide-y divide-dashed divide-espresso-700">
                {result.items.map((it, i) => {
                  const isEditing = editing.has(it.descripcion);
                  return (
                    <li
                      key={it.descripcion + i}
                      className="animate-fade px-5 py-4"
                      style={{ animationDelay: `${i * 50}ms` }}
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <p className="truncate font-mono text-sm font-medium text-sand-50">
                            {it.descripcion}
                          </p>
                          <p className="mt-0.5 text-xs text-sand-500">
                            {it.cantidad != null ? `${it.cantidad} und` : "—"}
                            {it.total != null ? ` · ${cop.format(it.total)}` : ""}
                          </p>
                        </div>

                        {it.reconocido && !isEditing ? (
                          <div className="flex shrink-0 items-center gap-3">
                            <div className="text-right">
                              <span className="inline-flex items-center gap-1 text-sm font-medium text-matched">
                                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                  <path d="M20 6 9 17l-5-5" />
                                </svg>
                                {it.product_name ?? "Asignado"}
                              </span>
                              {(it.factor ?? 1) !== 1 && it.cantidad != null && (
                                <p className="mt-0.5 text-[11px] text-amber">
                                  ×{it.factor} → {it.cantidad * (it.factor ?? 1)} und a inventario
                                </p>
                              )}
                            </div>
                            <button
                              onClick={() =>
                                setEditing((s) => new Set(s).add(it.descripcion))
                              }
                              className="text-xs text-sand-500 underline-offset-2 transition hover:text-amber hover:underline"
                            >
                              cambiar
                            </button>
                          </div>
                        ) : (
                          <span className="shrink-0 rounded-full bg-pending/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-pending">
                            sin asignar
                          </span>
                        )}
                      </div>

                      {(!it.reconocido || isEditing) && (
                        <div className="mt-3 flex items-start gap-2">
                          <label className="flex shrink-0 flex-col items-center">
                            <span className="mb-1 text-[10px] uppercase tracking-wide text-sand-500">
                              und/empaque
                            </span>
                            <input
                              type="number"
                              min={1}
                              step={1}
                              value={factores[it.descripcion] ?? it.factor ?? 1}
                              onChange={(e) =>
                                setFactores((f) => ({
                                  ...f,
                                  [it.descripcion]: Math.max(1, Number(e.target.value) || 1),
                                }))
                              }
                              title="Unidades de inventario por unidad facturada (ej. un six pack = 6)"
                              className="w-16 rounded-lg border border-espresso-600 bg-espresso-900/70 px-2 py-2 text-center text-sm text-sand-50 outline-none transition focus:border-amber focus:shadow-glow"
                            />
                          </label>
                          <div className="flex-1">
                            <ProductPicker
                              autoFocus={isEditing}
                              onPick={(p) =>
                                asignar(it.descripcion, p, factores[it.descripcion] ?? it.factor ?? 1)
                              }
                              placeholder={`Símil para “${it.descripcion}”…`}
                            />
                          </div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>

              {result.pendientes === 0 && (
                <div className="border-t border-dashed border-espresso-600 p-5">
                  {movResult ? (
                    <div className="flex flex-col items-center gap-3 text-center">
                      <p className="font-display text-lg text-matched">
                        {deleted ? "Compra deshecha en Loggro" : "Compra registrada en Loggro ✦"}
                      </p>
                      <p className="text-xs text-sand-500">
                        {movResult.items} ítems · {cop.format(movResult.total)}
                        {movResult.invoice_number ? ` · factura ${movResult.invoice_number}` : ""}
                        {movResult.movement_id
                          ? ` · mov …${movResult.movement_id.slice(-6)}`
                          : ""}
                      </p>
                      {!deleted && movResult.movement_id && (
                        <button
                          onClick={eliminarMovimiento}
                          disabled={deleting}
                          className="inline-flex items-center gap-2 rounded-xl border border-pending/50 bg-pending/10 px-4 py-2 text-sm font-semibold text-pending transition hover:bg-pending/20 disabled:opacity-60"
                        >
                          <svg
                            className="h-4 w-4" viewBox="0 0 24 24" fill="none"
                            stroke="currentColor" strokeWidth="2.2"
                          >
                            <path d="M3 7h18M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m-9 0v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7" />
                          </svg>
                          {deleting ? "Deshaciendo…" : "Deshacer (eliminar de Loggro)"}
                        </button>
                      )}
                      {deleted && (
                        <>
                          <p className="text-xs text-sand-500">
                            Se revirtió el stock y el costo promedio.
                          </p>
                          <button
                            onClick={() => {
                              setMovResult(null);
                              setDeleted(false);
                            }}
                            className="text-sm text-sand-400 underline-offset-4 transition hover:text-amber hover:underline"
                          >
                            Registrar de nuevo
                          </button>
                        </>
                      )}
                    </div>
                  ) : confirmCreate ? (
                    <div className="flex flex-col items-center gap-3 text-center">
                      <p className="max-w-md text-sm text-sand-200">
                        Se creará una <span className="font-semibold text-amber">Entrada - Compra</span>{" "}
                        por <span className="font-mono">{cop.format(totalCompra)}</span> con{" "}
                        {result.total} ítems{meta?.numero ? ` (factura ${meta.numero})` : ""}.
                      </p>
                      <p className="text-xs text-sand-500">
                        Afecta el stock y el costo promedio en Loggro. ¿Confirmar?
                      </p>
                      <div className="flex items-center gap-3">
                        <button
                          onClick={crearMovimiento}
                          disabled={creating}
                          className="inline-flex items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
                        >
                          {creating ? "Registrando…" : "Sí, registrar"}
                        </button>
                        <button
                          onClick={() => setConfirmCreate(false)}
                          disabled={creating}
                          className="text-sm text-sand-400 underline-offset-4 transition hover:text-sand-100 hover:underline disabled:opacity-60"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-3 text-center">
                      <p className="font-display text-lg text-matched">Todo homologado ✦</p>
                      <p className="text-xs text-sand-500">
                        Este proveedor ya quedó aprendido. Listo para registrar la compra en Loggro.
                      </p>
                      <button
                        onClick={() => setConfirmCreate(true)}
                        className="group inline-flex items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright"
                      >
                        Registrar compra en Loggro
                        <svg
                          className="h-4 w-4 transition group-hover:translate-x-0.5"
                          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                        >
                          <path d="M5 12h14M13 6l6 6-6 6" />
                        </svg>
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </div>
      </>
      )}

      <footer className="mt-12 text-center font-mono text-[11px] uppercase tracking-[0.3em] text-sand-500/60">
        Loggro · Restobar · api.pirpos.com
      </footer>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full min-h-[320px] animate-fade flex-col items-center justify-center rounded-2xl border border-dashed border-espresso-700 bg-espresso-900/30 p-10 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-2xl border border-espresso-600 bg-espresso-850 text-amber">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M6 2h9l5 5v15a0 0 0 0 1 0 0H6a0 0 0 0 1 0 0V2Z" />
          <path d="M14 2v6h6M9 13h6M9 17h6M9 9h2" />
        </svg>
      </span>
      <p className="mt-4 font-display text-lg text-sand-100">Aún no hay análisis</p>
      <p className="mt-1 max-w-xs text-sm text-sand-500">
        Elige un proveedor, pega los ítems de la tirilla y pulsa{" "}
        <span className="text-amber">Analizar</span>.
      </p>
    </div>
  );
}
