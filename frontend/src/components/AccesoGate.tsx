import { useEffect, useState } from "react";
import { api, EVENTO_SIN_ACCESO, type EstadoAcceso, type ModoAcceso } from "../api";

/**
 * Puerta de entrada a la app.
 *
 * Envuelve todo: hasta que no hay sesión no se monta nada de adentro. Ojo —
 * esto es comodidad de navegación, NO la protección. Quien protege es el
 * middleware del backend (acceso.py): los endpoints se pueden llamar con curl
 * sin pasar por esta pantalla.
 */
export default function AccesoGate({
  children,
}: {
  children: (modo: ModoAcceso, salir: () => void) => React.ReactNode;
}) {
  const [estado, setEstado] = useState<EstadoAcceso | null>(null);
  const [codigo, setCodigo] = useState("");
  const [entrando, setEntrando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const consultar = () =>
    api
      .acceso()
      .then(setEstado)
      .catch(() =>
        setEstado({ dentro: false, modo: null, configurado: true, demo_disponible: false })
      );

  useEffect(() => {
    consultar();
    // Si la cookie vence a mitad de sesión, cualquier llamada devuelve 401 y
    // volvemos aquí en vez de dejar la pantalla llena de errores.
    const volver = () => setEstado((e) => (e ? { ...e, dentro: false, modo: null } : e));
    window.addEventListener(EVENTO_SIN_ACCESO, volver);
    return () => window.removeEventListener(EVENTO_SIN_ACCESO, volver);
  }, []);

  const entrar = async (valor: string) => {
    setError(null);
    if (!valor.trim()) return setError("Escribe el código.");
    setEntrando(true);
    try {
      const r = await api.entrar(valor.trim());
      setEstado((e) => ({ ...(e as EstadoAcceso), dentro: true, modo: r.modo }));
      setCodigo("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEntrando(false);
    }
  };

  const entrarDemo = async () => {
    setError(null);
    setEntrando(true);
    try {
      const r = await api.entrarDemo();
      setEstado((e) => ({ ...(e as EstadoAcceso), dentro: true, modo: r.modo }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEntrando(false);
    }
  };

  const salir = async () => {
    await api.salir().catch(() => {});
    setEstado((e) => (e ? { ...e, dentro: false, modo: null } : e));
  };

  if (!estado) {
    return <div className="grid min-h-screen place-items-center text-sm text-sand-500">…</div>;
  }

  if (estado.dentro && estado.modo) {
    return (
      <>
        {estado.modo === "demo" && <CintaDemo />}
        {children(estado.modo, salir)}
      </>
    );
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="animate-rise w-full max-w-sm">
        <div className="text-center">
          <p className="font-mono text-[11px] uppercase tracking-[0.35em] text-amber">Loggro</p>
          <h1 className="mt-3 font-display text-3xl font-bold text-sand-50">Asistente de bar</h1>
          <p className="mt-2 text-sm leading-relaxed text-sand-500">
            Captura de compras y gastos por foto o voz, cartera e informe de utilidad,
            conectado a Loggro.
          </p>
        </div>

        {!estado.configurado ? (
          <p className="mt-8 rounded-xl border border-pending/40 bg-pending/10 px-4 py-3 text-sm text-pending">
            El acceso no está configurado en el servidor (falta <code>ACCESO_CODIGO</code>).
          </p>
        ) : (
          <>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                entrar(codigo);
              }}
              className="mt-8"
            >
              <label className="block">
                <span className="font-mono text-[11px] uppercase tracking-wider text-sand-500">
                  Código de acceso
                </span>
                <input
                  value={codigo}
                  onChange={(e) => setCodigo(e.target.value)}
                  type="password"
                  autoComplete="current-password"
                  autoFocus
                  placeholder="••••-•••••-•••••"
                  className="mt-1.5 w-full rounded-xl border border-espresso-600 bg-espresso-950/70 px-3 py-3 text-center font-mono text-sm tracking-wider text-sand-50 outline-none transition placeholder:text-sand-500/50 focus:border-amber focus:shadow-glow"
                />
              </label>

              {error && (
                <p className="mt-3 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-xs text-pending">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={entrando}
                className="mt-4 w-full rounded-xl bg-amber px-5 py-3 text-sm font-bold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
              >
                {entrando ? "Entrando…" : "Entrar"}
              </button>
            </form>

            {estado.demo_disponible && (
              <>
                <div className="my-5 flex items-center gap-3">
                  <span className="hairline h-px flex-1" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-sand-500/60">
                    o
                  </span>
                  <span className="hairline h-px flex-1" />
                </div>
                <button
                  onClick={entrarDemo}
                  disabled={entrando}
                  className="w-full rounded-xl border border-espresso-600 px-5 py-3 text-sm font-semibold text-sand-300 transition hover:border-amber hover:text-amber disabled:opacity-60"
                >
                  Explorar el demo
                </button>
                <p className="mt-2 text-center text-[11px] leading-relaxed text-sand-500/70">
                  Datos de un bar ficticio, solo lectura. No toca ninguna cuenta real.
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function CintaDemo() {
  return (
    <div className="sticky top-0 z-40 bg-amber px-4 py-1.5 text-center text-[11px] font-bold uppercase tracking-wider text-espresso-950">
      Modo demo · datos ficticios · solo lectura
    </div>
  );
}
