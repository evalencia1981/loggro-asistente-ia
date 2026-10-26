import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CrearInventarioResult,
  type LineaLista,
  type ListaLeida,
  type Product,
  type TipoInventario,
} from "../api";
import ImagenUpload from "./ImagenUpload";
import ProductPicker from "./ProductPicker";

const cop = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});
const num = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });

const hoyISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
};

const CONTEO = "conteo";

interface Linea {
  key: number;
  descripcion: string;
  product_id: string | null;
  product_name: string | null;
  origen: LineaLista["origen"] | "manual";
  cantidad: number;
  costo: number | null; // solo se usa en "Entrada con costo"
  stock: number | null;
}

const ORIGEN: Record<string, { txt: string; cls: string }> = {
  aprendido: { txt: "ya conocido", cls: "text-matched border-matched/40" },
  ia: { txt: "sugerido IA", cls: "text-amber border-amber/40" },
  parecido: { txt: "parecido, revisa", cls: "text-pending border-pending/40" },
  manual: { txt: "elegido", cls: "text-sand-400 border-espresso-600" },
};

let seq = 0;

export default function InventarioView() {
  const [tipos, setTipos] = useState<TipoInventario[]>([]);
  const [tipo, setTipo] = useState<string>(CONTEO);
  const [inputMode, setInputMode] = useState<"whatsapp" | "foto" | "manual">("whatsapp");
  const [texto, setTexto] = useState("");
  const [leyendo, setLeyendo] = useState(false);

  const [fecha, setFecha] = useState(hoyISO());
  const [nota, setNota] = useState("");
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [cambiando, setCambiando] = useState<number | null>(null);
  const [refrescando, setRefrescando] = useState(false);

  const [confirmar, setConfirmar] = useState(false);
  const [creando, setCreando] = useState(false);
  const [result, setResult] = useState<CrearInventarioResult | null>(null);
  const [deshaciendo, setDeshaciendo] = useState(false);
  const [deshecho, setDeshecho] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.inventarioTipos().then(setTipos).catch((e) => setError(String(e)));
  }, []);

  const esConteo = tipo === CONTEO;
  const tipoSel = tipos.find((t) => String(t.id) === tipo) || null;
  const pideCosto = tipoSel?.costo === "usuario";

  const reiniciarResultado = () => {
    setResult(null);
    setDeshecho(false);
    setConfirmar(false);
  };

  const aplicarLista = (r: ListaLeida) => {
    const nuevas: Linea[] = r.items.map((it) => ({
      key: ++seq,
      descripcion: it.descripcion,
      product_id: it.product_id,
      product_name: it.product_name,
      origen: it.origen,
      cantidad: it.cantidad || 0,
      costo: it.costo_unitario || null,
      stock: it.stock_actual,
    }));
    setLineas((prev) => [...prev, ...nuevas]);
    if (r.fecha) setFecha(r.fecha);
    if (r.nota && !nota) setNota(r.nota);
    reiniciarResultado();
    setError(null);
  };

  const leerTexto = async () => {
    if (!texto.trim()) return;
    setLeyendo(true);
    setError(null);
    try {
      aplicarLista(await api.inventarioListaTexto(texto));
      setTexto("");
    } catch (e) {
      setError(`No se pudo leer la lista: ${e}`);
    } finally {
      setLeyendo(false);
    }
  };

  const stockDe = async (ids: string[]) => {
    const r = await api.inventarioStock(ids);
    setLineas((prev) =>
      prev.map((l) => (l.product_id && r[l.product_id] ? { ...l, stock: r[l.product_id].stock } : l))
    );
  };

  const refrescarStock = async () => {
    const ids = lineas.map((l) => l.product_id).filter((x): x is string => !!x);
    if (!ids.length) return;
    setRefrescando(true);
    try {
      await stockDe(ids);
    } catch (e) {
      setError(`No se pudo leer el stock: ${e}`);
    } finally {
      setRefrescando(false);
    }
  };

  const elegir = (key: number, p: Product) => {
    setLineas((prev) =>
      prev.map((l) =>
        l.key === key ? { ...l, product_id: p.id, product_name: p.name, origen: "manual", stock: null } : l
      )
    );
    setCambiando(null);
    reiniciarResultado();
    stockDe([p.id]).catch(() => {});
  };

  const agregarManual = (p: Product) => {
    setLineas((prev) => [
      ...prev,
      { key: ++seq, descripcion: "", product_id: p.id, product_name: p.name, origen: "manual", cantidad: 0, costo: null, stock: null },
    ]);
    reiniciarResultado();
    stockDe([p.id]).catch(() => {});
  };

  const editar = (key: number, cambios: Partial<Linea>) => {
    setLineas((prev) => prev.map((l) => (l.key === key ? { ...l, ...cambios } : l)));
    reiniciarResultado();
  };

  const quitar = (key: number) => {
    setLineas((prev) => prev.filter((l) => l.key !== key));
    reiniciarResultado();
  };

  // Productos repetidos se suman (en el backend también): aquí solo se avisa.
  const repetidos = useMemo(() => {
    const vistos = new Map<string, number>();
    lineas.forEach((l) => l.product_id && vistos.set(l.product_id, (vistos.get(l.product_id) || 0) + 1));
    return new Set([...vistos].filter(([, n]) => n > 1).map(([id]) => id));
  }, [lineas]);

  const sinProducto = lineas.filter((l) => !l.product_id).length;
  const cantidadInvalida = lineas.some((l) => (esConteo ? l.cantidad < 0 : l.cantidad <= 0));

  // Resumen del conteo contra el stock que se ve en pantalla (el backend recalcula
  // con el stock del momento de registrar).
  const resumenConteo = useMemo(() => {
    const porProducto = new Map<string, { contado: number; stock: number | null }>();
    lineas.forEach((l) => {
      if (!l.product_id) return;
      const prev = porProducto.get(l.product_id);
      porProducto.set(l.product_id, {
        contado: (prev?.contado || 0) + (l.cantidad || 0),
        stock: l.stock,
      });
    });
    let suben = 0, bajan = 0, iguales = 0;
    porProducto.forEach(({ contado, stock }) => {
      if (stock == null) return;
      if (contado > stock) suben++;
      else if (contado < stock) bajan++;
      else iguales++;
    });
    return { suben, bajan, iguales };
  }, [lineas]);

  const registrar = async () => {
    setError(null);
    if (!lineas.length) return setError("Agrega al menos un producto.");
    if (sinProducto) return setError(`Hay ${sinProducto} línea(s) sin producto de Loggro. Elige el producto o quítalas.`);
    if (cantidadInvalida)
      return setError(esConteo ? "Hay conteos negativos." : "Todas las cantidades deben ser mayores a cero.");
    if (pideCosto && lineas.some((l) => l.costo == null || l.costo < 0))
      return setError("En 'Entrada con costo' cada producto necesita su costo unitario.");
    setCreando(true);
    try {
      const r = await api.crearInventario({
        tipo,
        fecha,
        nota,
        items: lineas.map((l) => ({
          descripcion: l.descripcion,
          product_id: l.product_id as string,
          cantidad: l.cantidad,
          costo_unitario: pideCosto ? l.costo : null,
        })),
      });
      setResult(r);
      setConfirmar(false);
      setDeshecho(false);
    } catch (e) {
      setError(`No se pudo registrar: ${e}`);
    } finally {
      setCreando(false);
    }
  };

  const deshacer = async () => {
    if (!result) return;
    setDeshaciendo(true);
    setError(null);
    try {
      for (const m of result.movimientos) {
        if (m.movement_id) await api.eliminarMovimiento(m.movement_id);
      }
      setDeshecho(true);
    } catch (e) {
      setError(`No se pudo deshacer: ${e}`);
    } finally {
      setDeshaciendo(false);
    }
  };

  const nuevo = () => {
    setLineas([]);
    setNota("");
    setFecha(hoyISO());
    reiniciarResultado();
    setError(null);
  };

  const entradas = tipos.filter((t) => !t.resta);
  const salidas = tipos.filter((t) => t.resta);

  return (
    <div className="grid gap-6 lg:grid-cols-12">
      {/* Tipo + captura */}
      <section className="lg:col-span-5">
        <div className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-5 shadow-panel">
          <h2 className="font-display text-lg font-semibold text-sand-50">1 · Movimiento</h2>
          <label className="mt-3 flex flex-col gap-1">
            <span className="text-xs text-sand-400">Tipo</span>
            <select
              value={tipo}
              onChange={(e) => {
                setTipo(e.target.value);
                reiniciarResultado();
              }}
              className={inputCls}
            >
              <option value={CONTEO}>Conteo físico / Inventario inicial</option>
              <optgroup label="Entradas (suman)">
                {entradas.map((t) => (
                  <option key={t.id} value={String(t.id)}>{t.nombre}</option>
                ))}
              </optgroup>
              <optgroup label="Salidas (restan)">
                {salidas.map((t) => (
                  <option key={t.id} value={String(t.id)}>{t.nombre}</option>
                ))}
              </optgroup>
            </select>
          </label>
          <p className="mt-2 text-xs leading-relaxed text-sand-500">
            {esConteo
              ? "Escribe lo que HAY físicamente. La app lo compara con el stock de Loggro y crea una Entrada-Ajuste por lo que sobra y una Salida-Ajuste por lo que falta. Los productos que no estén en la lista no se tocan."
              : tipoSel?.ayuda || (tipoSel?.resta ? "Las cantidades se restan del stock." : "Las cantidades se suman al stock.")}
          </p>

          <div className="mt-5 flex items-center justify-between gap-3">
            <h3 className="font-display text-base font-semibold text-sand-50">2 · Lista</h3>
            <div className="inline-flex rounded-lg border border-espresso-600 bg-espresso-950/50 p-0.5 text-xs">
              {([
                ["whatsapp", "💬 WhatsApp"],
                ["foto", "📷 Foto"],
                ["manual", "✍️ Manual"],
              ] as const).map(([m, txt]) => (
                <button
                  key={m}
                  onClick={() => setInputMode(m)}
                  className={`rounded-md px-3 py-1 font-medium transition ${
                    inputMode === m ? "bg-amber text-espresso-950" : "text-sand-400 hover:text-amber"
                  }`}
                >
                  {txt}
                </button>
              ))}
            </div>
          </div>
          <p className="mb-3 mt-1 text-xs text-sand-500">
            {inputMode === "whatsapp"
              ? "Copia el mensaje del grupo y pégalo tal cual: la IA ignora horas, nombres y saludos."
              : inputMode === "foto"
              ? "Foto de la lista escrita a mano, de la planilla o un pantallazo del chat."
              : "Busca cada producto y escribe la cantidad en la tabla."}
          </p>

          {inputMode === "whatsapp" ? (
            <div className="flex flex-col gap-3">
              <textarea
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                rows={9}
                placeholder={"Conteo barra 28/09\naguila 140\npoker 58\n3 guaros antioqueño\ncocacola 12"}
                className={`${inputCls} resize-y font-mono`}
              />
              <button
                onClick={leerTexto}
                disabled={leyendo || !texto.trim()}
                className="inline-flex w-fit items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
              >
                {leyendo ? "Leyendo…" : "Leer lista"}
              </button>
            </div>
          ) : inputMode === "foto" ? (
            <ImagenUpload<ListaLeida>
              extraer={api.inventarioListaImagen}
              onResult={aplicarLista}
              etiqueta="Toca para tomar/subir la foto de la lista"
            />
          ) : (
            <ProductPicker onPick={agregarManual} placeholder="Buscar producto para agregar…" />
          )}
        </div>
      </section>

      {/* Revisión */}
      <section className="lg:col-span-7">
        <div className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-5 shadow-panel [animation-delay:80ms]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-lg font-semibold text-sand-50">3 · Revisar y registrar</h2>
            {lineas.length > 0 && (
              <div className="flex gap-2">
                <button onClick={refrescarStock} disabled={refrescando} className={chipCls}>
                  {refrescando ? "Leyendo stock…" : "↻ Stock"}
                </button>
                <button onClick={nuevo} className={chipCls}>Limpiar</button>
              </div>
            )}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-4">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-sand-400">Fecha</span>
              <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-sand-400">Nota</span>
              <input
                value={nota}
                onChange={(e) => setNota(e.target.value)}
                placeholder={esConteo ? "Conteo físico" : "opcional"}
                className={inputCls}
              />
            </label>
          </div>

          {lineas.length === 0 ? (
            <p className="mt-6 rounded-xl border border-dashed border-espresso-600 px-4 py-8 text-center text-sm text-sand-500">
              Aún no hay productos. Pega la lista, sube una foto o agrégalos a mano.
            </p>
          ) : (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[560px] text-sm">
                <thead>
                  <tr className="text-left text-xs text-sand-500">
                    <th className="pb-2 font-medium">Producto</th>
                    <th className="pb-2 text-right font-medium">Stock</th>
                    <th className="pb-2 text-right font-medium">{esConteo ? "Contado" : "Cantidad"}</th>
                    {esConteo && <th className="pb-2 text-right font-medium">Ajuste</th>}
                    {pideCosto && <th className="pb-2 text-right font-medium">Costo unit.</th>}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {lineas.map((l) => {
                    const dif = l.stock == null ? null : (l.cantidad || 0) - l.stock;
                    const o = ORIGEN[l.origen || ""];
                    return (
                      <tr key={l.key} className="border-t border-espresso-700/70 align-top">
                        <td className="py-2 pr-3">
                          {cambiando === l.key || !l.product_id ? (
                            <div className="flex flex-col gap-1">
                              {l.descripcion && (
                                <span className="text-xs text-pending">
                                  “{l.descripcion}” {l.product_id ? "" : "— sin producto"}
                                </span>
                              )}
                              <ProductPicker
                                autoFocus={cambiando === l.key}
                                onPick={(p) => elegir(l.key, p)}
                                placeholder="Buscar en Loggro…"
                              />
                            </div>
                          ) : (
                            <div className="flex flex-col gap-0.5">
                              <button
                                onClick={() => setCambiando(l.key)}
                                title="Cambiar producto"
                                className="w-fit text-left font-medium text-sand-50 hover:text-amber"
                              >
                                {l.product_name}
                              </button>
                              <span className="flex flex-wrap items-center gap-1.5 text-[11px] text-sand-500">
                                {l.descripcion && <span>“{l.descripcion}”</span>}
                                {o && <span className={`rounded border px-1.5 ${o.cls}`}>{o.txt}</span>}
                                {l.product_id && repetidos.has(l.product_id) && (
                                  <span className="rounded border border-amber/40 px-1.5 text-amber">se suma</span>
                                )}
                              </span>
                            </div>
                          )}
                        </td>
                        <td className="py-2 text-right font-mono text-sand-400">
                          {l.stock == null ? "—" : num.format(l.stock)}
                        </td>
                        <td className="py-2 text-right">
                          <input
                            type="number"
                            step="any"
                            min={0}
                            value={Number.isFinite(l.cantidad) ? l.cantidad : 0}
                            onChange={(e) => editar(l.key, { cantidad: Number(e.target.value) || 0 })}
                            className="w-20 rounded-lg border border-espresso-600 bg-espresso-900/70 px-2 py-1 text-right font-mono text-sand-50 outline-none focus:border-amber"
                          />
                        </td>
                        {esConteo && (
                          <td
                            className={`py-2 text-right font-mono ${
                              dif == null ? "text-sand-500" : dif > 0 ? "text-matched" : dif < 0 ? "text-pending" : "text-sand-500"
                            }`}
                          >
                            {dif == null ? "—" : dif === 0 ? "=" : `${dif > 0 ? "+" : ""}${num.format(dif)}`}
                          </td>
                        )}
                        {pideCosto && (
                          <td className="py-2 text-right">
                            <input
                              type="number"
                              min={0}
                              value={l.costo ?? ""}
                              onChange={(e) =>
                                editar(l.key, { costo: e.target.value === "" ? null : Number(e.target.value) })
                              }
                              className="w-24 rounded-lg border border-espresso-600 bg-espresso-900/70 px-2 py-1 text-right font-mono text-sand-50 outline-none focus:border-amber"
                            />
                          </td>
                        )}
                        <td className="py-2 pl-2 text-right">
                          <button onClick={() => quitar(l.key)} title="Quitar" className="text-sand-500 hover:text-pending">
                            ✕
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {lineas.length > 0 && (
            <p className="mt-3 text-xs text-sand-500">
              {lineas.length} línea(s)
              {sinProducto > 0 && <span className="text-pending"> · {sinProducto} sin producto</span>}
              {esConteo && (
                <>
                  {" · "}
                  <span className="text-matched">{resumenConteo.suben} suben</span>
                  {" · "}
                  <span className="text-pending">{resumenConteo.bajan} bajan</span>
                  {" · "}
                  {resumenConteo.iguales} iguales
                </>
              )}
            </p>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {result ? (
              <div className="flex w-full flex-col gap-2">
                <p className="font-display text-lg text-matched">
                  {deshecho
                    ? "Movimiento deshecho en Loggro"
                    : result.movimientos.length
                    ? "Registrado en Loggro ✦"
                    : "Nada que ajustar: el conteo coincide con Loggro"}
                </p>
                {result.movimientos.map((m) => (
                  <p key={m.movement_id || m.tipo} className="text-xs text-sand-500">
                    {m.tipo_nombre} · {m.items} producto(s)
                    {m.total != null ? ` · ${cop.format(Math.abs(m.total))}` : ""}
                    {m.movement_id ? ` · …${m.movement_id.slice(-6)}` : ""}
                  </p>
                ))}
                {result.sin_cambio ? (
                  <p className="text-xs text-sand-500">{result.sin_cambio} producto(s) ya estaban iguales.</p>
                ) : null}
                <div className="mt-1 flex flex-wrap gap-2">
                  {!deshecho && result.movimientos.some((m) => m.movement_id) && (
                    <button
                      onClick={deshacer}
                      disabled={deshaciendo}
                      className="inline-flex w-fit items-center gap-2 rounded-xl border border-pending/50 bg-pending/10 px-4 py-2 text-sm font-semibold text-pending transition hover:bg-pending/20 disabled:opacity-60"
                    >
                      {deshaciendo ? "Deshaciendo…" : "Deshacer (eliminar de Loggro)"}
                    </button>
                  )}
                  <button onClick={nuevo} className={chipCls}>Nuevo movimiento</button>
                </div>
              </div>
            ) : confirmar ? (
              <div className="flex w-full flex-col gap-3 rounded-xl border border-amber/40 bg-amber/5 p-4">
                <p className="text-sm text-sand-100">
                  {esConteo
                    ? `Se ajustará el stock de ${lineas.length} línea(s) al valor contado (fecha ${fecha}).`
                    : `Se registrará “${tipoSel?.nombre}” con ${lineas.length} línea(s) (fecha ${fecha}).`}
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={registrar}
                    disabled={creando}
                    className="inline-flex items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
                  >
                    {creando ? "Registrando…" : "Sí, registrar"}
                  </button>
                  <button onClick={() => setConfirmar(false)} className={chipCls}>Cancelar</button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmar(true)}
                disabled={!lineas.length}
                className="inline-flex items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
              >
                Registrar en Loggro
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

const chipCls =
  "rounded-full border border-espresso-600 bg-espresso-850 px-3 py-1.5 text-xs font-semibold text-sand-100 transition hover:border-amber hover:text-amber disabled:opacity-60";
