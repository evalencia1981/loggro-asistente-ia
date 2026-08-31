import { useEffect, useMemo, useState } from "react";
import {
  api,
  type Periodicidad,
  type Provider,
  type Recurrente,
  type SugerenciaRecurrente,
  type TipoGasto,
} from "../api";

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

const PERIODICIDADES: { valor: Periodicidad; etiqueta: string }[] = [
  { valor: "semanal", etiqueta: "Semanal" },
  { valor: "quincenal", etiqueta: "Quincenal" },
  { valor: "mensual", etiqueta: "Mensual" },
  { valor: "libre", etiqueta: "Sin periodo fijo" },
];

/** "hace 8 días" / "hoy" / "nunca". El aviso es informativo: nada se crea solo. */
function desdeCuando(dias: number | null): string {
  if (dias === null) return "sin pagos aún";
  if (dias <= 0) return "hoy";
  if (dias === 1) return "ayer";
  return `hace ${dias} días`;
}

const vacio = (): Borrador => ({
  nombre: "",
  concepto: "",
  type_expense_id: "",
  provider_id: "",
  forma_pago: "",
  sale_de_caja: false,
  monto_sugerido: 0,
  periodicidad: "libre",
  notas: "",
});

interface Borrador {
  id?: string;
  nombre: string;
  concepto: string;
  type_expense_id: string;
  provider_id: string;
  forma_pago: string;
  sale_de_caja: boolean;
  monto_sugerido: number;
  periodicidad: Periodicidad;
  notas: string;
}

/**
 * Beneficiarios recurrentes: nómina y pagos que se repiten.
 *
 * Lo recurrente aquí es la PERSONA, no el monto ni la fecha. En el historial de
 * Loggro un mismo pago aparece escrito de seis formas ("Nomina Simon", "Pago
 * simon", "simon nomina 09/05"), lo que impide totalizar por persona; y los
 * montos de un mismo beneficiario van de 25.500 a 144.500, así que programarlos
 * sería inventar cifras. Por eso se guarda el concepto y el tipo de gasto, y el
 * monto se digita en cada pago.
 */
export default function RecurrentesPanel({
  tipos,
  providers,
  onAplicar,
}: {
  tipos: TipoGasto[];
  providers: Provider[];
  onAplicar: (r: Recurrente) => void;
}) {
  const [items, setItems] = useState<Recurrente[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [editando, setEditando] = useState<Borrador | null>(null);
  const [diaDePago, setDiaDePago] = useState(false);
  const [sugerencias, setSugerencias] = useState<SugerenciaRecurrente[] | null>(null);
  const [buscando, setBuscando] = useState(false);

  const cargar = () => {
    setCargando(true);
    api
      .recurrentes()
      .then((r) => setItems(r.items))
      .catch((e) => setError(String(e)))
      .finally(() => setCargando(false));
  };

  useEffect(cargar, []);

  const guardar = async (b: Borrador) => {
    setError(null);
    setAviso(null);
    if (!b.nombre.trim()) return setError("El nombre es obligatorio.");
    if (!b.type_expense_id) return setError("El tipo de gasto es obligatorio.");
    try {
      const r = await api.guardarRecurrente({
        ...b,
        provider_id: b.provider_id || null,
        monto_sugerido: Math.round(b.monto_sugerido || 0),
      });
      if (r.aviso) setAviso(r.aviso);
      setEditando(null);
      cargar();
    } catch (e) {
      setError(`No se pudo guardar: ${e}`);
    }
  };

  const borrar = async (r: Recurrente) => {
    // Se pregunta porque quitar un beneficiario borra su monto sugerido y su
    // historial de "último pago"; los gastos ya registrados no se tocan.
    if (!window.confirm(`¿Quitar "${r.nombre}" de la lista? Los gastos ya registrados no se tocan.`))
      return;
    setError(null);
    try {
      const out = await api.eliminarRecurrente(r.id);
      if (out.aviso) setAviso(out.aviso);
      cargar();
    } catch (e) {
      setError(`No se pudo quitar: ${e}`);
    }
  };

  const buscarSugerencias = async () => {
    setBuscando(true);
    setError(null);
    try {
      const r = await api.sugerenciasRecurrentes(180);
      setSugerencias(r.sugerencias.filter((s) => !s.ya_registrado));
    } catch (e) {
      setError(`No se pudo leer el historial: ${e}`);
    } finally {
      setBuscando(false);
    }
  };

  const pendientes = items.filter((r) => r.vencido).length;

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setDiaDePago(true)}
          disabled={items.length === 0}
          className="inline-flex items-center gap-2 rounded-xl bg-amber px-3.5 py-2 text-xs font-bold text-espresso-950 transition hover:bg-amber-bright disabled:cursor-not-allowed disabled:opacity-40"
        >
          Día de pago
          {pendientes > 0 && (
            <span className="rounded-full bg-espresso-950/25 px-1.5 py-0.5 font-mono text-[10px]">
              {pendientes}
            </span>
          )}
        </button>
        <button
          onClick={() => setEditando(vacio())}
          className="rounded-xl border border-espresso-600 px-3.5 py-2 text-xs font-semibold text-sand-300 transition hover:border-amber hover:text-amber"
        >
          + Beneficiario
        </button>
        <button
          onClick={buscarSugerencias}
          disabled={buscando}
          title="Lee tus gastos de los últimos 6 meses y propone quiénes se repiten"
          className="rounded-xl border border-espresso-600 px-3.5 py-2 text-xs font-semibold text-sand-400 transition hover:border-amber hover:text-amber disabled:opacity-50"
        >
          {buscando ? "Leyendo historial…" : "Buscar en mi historial"}
        </button>
      </div>

      {aviso && (
        <p className="mt-3 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-[11px] text-pending">
          {aviso}
        </p>
      )}
      {error && (
        <p className="mt-3 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-sm text-pending">
          {error}
        </p>
      )}

      {sugerencias && (
        <Sugerencias
          lista={sugerencias}
          onCerrar={() => setSugerencias(null)}
          onAgregar={(s) =>
            setEditando({
              ...vacio(),
              nombre: s.nombre,
              concepto: s.nombre,
              type_expense_id: s.type_expense_id || "",
              monto_sugerido: s.monto_sugerido,
            })
          }
        />
      )}

      <div className="mt-4">
        {cargando ? (
          <p className="text-xs text-sand-500">Cargando…</p>
        ) : items.length === 0 ? (
          <p className="rounded-xl border border-dashed border-espresso-600 px-4 py-6 text-center text-xs text-sand-500">
            Aún no hay beneficiarios. Usa <span className="text-sand-300">Buscar en mi historial</span>{" "}
            para traer los que ya se repiten en Loggro.
          </p>
        ) : (
          <ul className="grid gap-2">
            {items.map((r) => (
              <li key={r.id}>
                <div className="flex items-stretch gap-1">
                  {/* Tocar el nombre llena el formulario de gasto; los iconos
                      van fuera del botón para no anidar botones. */}
                  <button
                    onClick={() => onAplicar(r)}
                    className="group min-w-0 flex-1 rounded-xl border border-espresso-600 bg-espresso-950/40 px-3 py-2.5 text-left transition hover:border-amber hover:bg-espresso-850/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-semibold text-sand-100 group-hover:text-amber">
                        {r.nombre}
                      </span>
                      <span className="shrink-0 font-mono text-xs text-sand-300">
                        {r.monto_sugerido > 0 ? cop.format(r.monto_sugerido) : "—"}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px]">
                      <span className={r.vencido ? "text-pending" : "text-sand-500"}>
                        {desdeCuando(r.dias_desde_ultimo)}
                      </span>
                      {r.periodicidad !== "libre" && (
                        <span className="text-sand-500/70">· {r.periodicidad}</span>
                      )}
                    </div>
                  </button>
                  <button
                    onClick={() => setEditando({ ...r, provider_id: r.provider_id || "" })}
                    aria-label={`Editar ${r.nombre}`}
                    className="shrink-0 rounded-xl border border-espresso-600 px-2.5 text-sand-500 transition hover:border-amber hover:text-amber"
                  >
                    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
                    </svg>
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editando && (
        <ModalBeneficiario
          borrador={editando}
          tipos={tipos}
          providers={providers}
          onCambio={setEditando}
          onGuardar={() => guardar(editando)}
          onBorrar={editando.id ? () => {
            const r = items.find((i) => i.id === editando.id);
            if (r) { setEditando(null); borrar(r); }
          } : undefined}
          onCerrar={() => setEditando(null)}
        />
      )}

      {diaDePago && (
        <ModalDiaDePago
          items={items}
          onCerrar={() => setDiaDePago(false)}
          onListo={() => { setDiaDePago(false); cargar(); }}
        />
      )}
    </div>
  );
}

/* --------------------------------------------------------------------------- */
/* Sugerencias leídas del historial                                            */
/* --------------------------------------------------------------------------- */
function Sugerencias({
  lista,
  onAgregar,
  onCerrar,
}: {
  lista: SugerenciaRecurrente[];
  onAgregar: (s: SugerenciaRecurrente) => void;
  onCerrar: () => void;
}) {
  return (
    <div className="animate-rise mt-3 rounded-xl border border-espresso-600 bg-espresso-950/50 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-[11px] uppercase tracking-wider text-amber">
          {lista.length} se repiten en tus gastos
        </p>
        <button onClick={onCerrar} className="text-xs text-sand-500 hover:text-sand-100">
          Cerrar
        </button>
      </div>
      {lista.length === 0 ? (
        <p className="mt-2 text-[11px] text-sand-500">
          No encontré nada nuevo: ya tienes registrado lo que se repite.
        </p>
      ) : (
        <>
          <p className="mt-1 text-[11px] text-sand-500">
            El monto sugerido es la mediana de lo pagado, no el último valor. Revisa el nombre
            antes de guardar: el historial trae variantes de la misma persona.
          </p>
          <ul className="mt-2 grid gap-1.5">
            {lista.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => onAgregar(s)}
                  className="w-full rounded-lg border border-espresso-700 px-3 py-2 text-left transition hover:border-amber hover:bg-espresso-850/60"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm text-sand-100">{s.nombre}</span>
                    <span className="shrink-0 font-mono text-xs text-sand-300">
                      {cop.format(s.monto_sugerido)}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-sand-500">
                    {s.veces} veces · {s.tipo_nombre || "sin tipo"} · {desdeCuando(s.dias_desde_ultimo)}
                    {s.monto_min !== s.monto_max && (
                      <> · entre {cop.format(s.monto_min)} y {cop.format(s.monto_max)}</>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/* --------------------------------------------------------------------------- */
/* Alta / edición de un beneficiario                                           */
/* --------------------------------------------------------------------------- */
function ModalBeneficiario({
  borrador: b,
  tipos,
  providers,
  onCambio,
  onGuardar,
  onBorrar,
  onCerrar,
}: {
  borrador: Borrador;
  tipos: TipoGasto[];
  providers: Provider[];
  onCambio: (b: Borrador) => void;
  onGuardar: () => void;
  onBorrar?: () => void;
  onCerrar: () => void;
}) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onCerrar();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onCerrar]);

  const set = <K extends keyof Borrador>(k: K, v: Borrador[K]) => onCambio({ ...b, [k]: v });

  return (
    <Modal titulo={b.id ? "Editar beneficiario" : "Nuevo beneficiario"} onCerrar={onCerrar}>
      <div className="grid grid-cols-2 gap-4">
        <Campo label="Nombre *" full>
          <input value={b.nombre} onChange={(e) => set("nombre", e.target.value)} className={input} />
        </Campo>

        <Campo label="Concepto del gasto" full>
          <input
            value={b.concepto}
            onChange={(e) => set("concepto", e.target.value)}
            placeholder={b.nombre ? `Nómina ${b.nombre}` : "Nómina Simón"}
            className={input}
          />
          <span className="mt-1 block text-[11px] text-sand-500">
            Este texto se escribe igual en todos sus gastos. Es lo que permite sumar por persona
            después. Vacío = se usa el nombre.
          </span>
        </Campo>

        <Campo label="Tipo de gasto *" full>
          <select
            value={b.type_expense_id}
            onChange={(e) => set("type_expense_id", e.target.value)}
            className={input}
          >
            <option value="">— Selecciona —</option>
            {tipos.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </Campo>

        <Campo label="Monto sugerido">
          <input
            type="number"
            value={b.monto_sugerido}
            onChange={(e) => set("monto_sugerido", Number(e.target.value) || 0)}
            className={input}
          />
        </Campo>

        <Campo label="Periodicidad">
          <select
            value={b.periodicidad}
            onChange={(e) => set("periodicidad", e.target.value as Periodicidad)}
            className={input}
          >
            {PERIODICIDADES.map((p) => (
              <option key={p.valor} value={p.valor}>{p.etiqueta}</option>
            ))}
          </select>
          <span className="mt-1 block text-[11px] text-sand-500">
            Solo sirve para avisarte. Nunca crea un gasto solo.
          </span>
        </Campo>

        <Campo label="Proveedor">
          <select
            value={b.provider_id}
            onChange={(e) => set("provider_id", e.target.value)}
            className={input}
          >
            <option value="">— (opcional) —</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </Campo>

        <Campo label="Forma de pago">
          <input
            value={b.forma_pago}
            onChange={(e) => set("forma_pago", e.target.value)}
            placeholder="efectivo, transferencia…"
            className={input}
          />
        </Campo>

        <div className="col-span-2 flex items-center gap-3">
          <Switch on={b.sale_de_caja} onClick={() => set("sale_de_caja", !b.sale_de_caja)} />
          <span className="text-sm text-sand-200">Sale de caja</span>
          <span className="text-xs text-sand-500">(descuenta de la caja abierta)</span>
        </div>
      </div>

      <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
        {onBorrar ? (
          <button
            onClick={onBorrar}
            className="rounded-xl border border-pending/40 px-4 py-2.5 text-sm font-semibold text-pending transition hover:bg-pending/10"
          >
            Quitar de la lista
          </button>
        ) : (
          <span />
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <button
            onClick={onCerrar}
            className="rounded-xl border border-espresso-600 px-4 py-2.5 text-sm font-semibold text-sand-400 transition hover:border-sand-500 hover:text-sand-100"
          >
            Cancelar
          </button>
          <button
            onClick={onGuardar}
            className="rounded-xl bg-amber px-5 py-2.5 text-sm font-bold text-espresso-950 transition hover:bg-amber-bright"
          >
            Guardar
          </button>
        </div>
      </div>
    </Modal>
  );
}

/* --------------------------------------------------------------------------- */
/* Día de pago: un gasto por beneficiario                                      */
/* --------------------------------------------------------------------------- */
function ModalDiaDePago({
  items,
  onCerrar,
  onListo,
}: {
  items: Recurrente[];
  onCerrar: () => void;
  onListo: () => void;
}) {
  // Arranca con los vencidos marcados: si nada está vencido, nada marcado.
  // Marcar todo por defecto invitaría a registrar pagos que no ocurrieron.
  const [marcados, setMarcados] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(items.map((r) => [r.id, r.vencido]))
  );
  const [montos, setMontos] = useState<Record<string, number>>(() =>
    Object.fromEntries(items.map((r) => [r.id, r.monto_sugerido]))
  );
  const [fecha, setFecha] = useState(hoyISO());
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState<Awaited<ReturnType<typeof api.crearGastosLote>> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const lineas = useMemo(
    () => items.filter((r) => marcados[r.id] && (montos[r.id] || 0) > 0),
    [items, marcados, montos]
  );
  const total = lineas.reduce((s, r) => s + (montos[r.id] || 0), 0);

  const registrar = async () => {
    setError(null);
    setEnviando(true);
    try {
      const r = await api.crearGastosLote({
        lineas: lineas.map((l) => ({ recurrente_id: l.id, monto: Math.round(montos[l.id]) })),
        fecha,
      });
      setResultado(r);
    } catch (e) {
      setError(`No se pudo registrar: ${e}`);
    } finally {
      setEnviando(false);
    }
  };

  if (resultado) {
    return (
      <Modal titulo="Resultado" onCerrar={onListo}>
        <p className="font-display text-lg text-sand-50">
          {resultado.creados} {resultado.creados === 1 ? "gasto registrado" : "gastos registrados"} ·{" "}
          {cop.format(resultado.total)}
        </p>
        {resultado.fallidos > 0 && (
          <p className="mt-1 text-sm text-pending">
            {resultado.fallidos} no {resultado.fallidos === 1 ? "entró" : "entraron"}.
          </p>
        )}
        <ul className="mt-4 grid gap-1.5">
          {resultado.detalle.map((d) => (
            <li
              key={d.recurrente_id}
              className="flex items-start justify-between gap-3 rounded-lg border border-espresso-700 px-3 py-2 text-sm"
            >
              <span className="text-sand-100">{d.nombre}</span>
              {d.ok ? (
                <span className="shrink-0 font-mono text-xs text-matched">
                  {cop.format(d.total || 0)}
                </span>
              ) : (
                <span className="shrink-0 text-right text-[11px] text-pending">{d.error}</span>
              )}
            </li>
          ))}
        </ul>
        <button
          onClick={onListo}
          className="mt-5 w-full rounded-xl bg-amber px-5 py-2.5 text-sm font-bold text-espresso-950 transition hover:bg-amber-bright"
        >
          Listo
        </button>
      </Modal>
    );
  }

  return (
    <Modal titulo="Día de pago" onCerrar={onCerrar}>
      <p className="-mt-1 text-xs text-sand-500">
        Se crea un gasto separado por persona, con su concepto de siempre. Marca a quién le pagas
        y ajusta el monto.
      </p>

      <label className="mt-4 block">
        <span className="font-mono text-[11px] uppercase tracking-wider text-sand-500">Fecha</span>
        <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} className={`mt-1.5 ${input}`} />
      </label>

      <ul className="mt-4 grid gap-1.5">
        {items.map((r) => {
          const on = !!marcados[r.id];
          return (
            <li
              key={r.id}
              className={`flex items-center gap-3 rounded-xl border px-3 py-2 transition ${
                on ? "border-amber/50 bg-amber/5" : "border-espresso-700"
              }`}
            >
              <button
                onClick={() => setMarcados({ ...marcados, [r.id]: !on })}
                aria-pressed={on}
                aria-label={`${on ? "Quitar" : "Incluir"} ${r.nombre}`}
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border transition ${
                  on ? "border-amber bg-amber text-espresso-950" : "border-espresso-600"
                }`}
              >
                {on && (
                  <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5">
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                )}
              </button>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-sand-100">{r.nombre}</p>
                <p className={`text-[11px] ${r.vencido ? "text-pending" : "text-sand-500"}`}>
                  {desdeCuando(r.dias_desde_ultimo)}
                </p>
              </div>
              <input
                type="number"
                value={montos[r.id] ?? 0}
                onChange={(e) => setMontos({ ...montos, [r.id]: Number(e.target.value) || 0 })}
                disabled={!on}
                aria-label={`Monto para ${r.nombre}`}
                className="w-32 shrink-0 rounded-lg border border-espresso-600 bg-espresso-950/70 px-2 py-1.5 text-right font-mono text-sm text-sand-50 outline-none transition focus:border-amber disabled:opacity-40"
              />
            </li>
          );
        })}
      </ul>

      {error && (
        <p className="mt-3 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-sm text-pending">
          {error}
        </p>
      )}

      <div className="mt-5 flex items-center justify-between gap-4 border-t border-dashed border-espresso-700 pt-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-wider text-sand-500">Total</p>
          <p className="font-display text-xl font-bold text-sand-50">{cop.format(total)}</p>
        </div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <button
            onClick={onCerrar}
            className="rounded-xl border border-espresso-600 px-4 py-2.5 text-sm font-semibold text-sand-400 transition hover:border-sand-500 hover:text-sand-100"
          >
            Cancelar
          </button>
          <button
            onClick={registrar}
            disabled={enviando || lineas.length === 0}
            className="rounded-xl bg-amber px-5 py-2.5 text-sm font-bold text-espresso-950 transition hover:bg-amber-bright disabled:cursor-not-allowed disabled:opacity-40"
          >
            {enviando
              ? "Registrando…"
              : `Registrar ${lineas.length} ${lineas.length === 1 ? "gasto" : "gastos"}`}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/* --------------------------------------------------------------------------- */
/* Piezas compartidas                                                          */
/* --------------------------------------------------------------------------- */
function Modal({
  titulo,
  children,
  onCerrar,
}: {
  titulo: string;
  children: React.ReactNode;
  onCerrar: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-espresso-950/80 p-4 backdrop-blur-sm sm:items-center"
      onClick={onCerrar}
      role="dialog"
      aria-modal="true"
      aria-label={titulo}
    >
      <div
        className="animate-rise max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-espresso-700 bg-espresso-900 p-6 shadow-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h3 className="font-display text-xl font-bold text-sand-50">{titulo}</h3>
          <button
            onClick={onCerrar}
            aria-label="Cerrar"
            className="shrink-0 rounded-lg p-1.5 text-sand-500 transition hover:bg-espresso-850 hover:text-sand-100"
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

const input =
  "w-full appearance-none rounded-xl border border-espresso-600 bg-espresso-950/70 px-3 py-2.5 text-sm text-sand-50 outline-none transition focus:border-amber focus:shadow-glow";

function Campo({ label, children, full }: { label: string; children: React.ReactNode; full?: boolean }) {
  return (
    <label className={`flex flex-col gap-1 ${full ? "col-span-2" : ""}`}>
      <span className="text-xs text-sand-400">{label}</span>
      {children}
    </label>
  );
}

function Switch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={`relative h-6 w-11 shrink-0 rounded-full transition ${on ? "bg-amber" : "bg-espresso-700"}`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-sand-50 transition ${
          on ? "left-[22px]" : "left-0.5"
        }`}
      />
    </button>
  );
}
