import { useEffect, useState } from "react";
import { api, type Modulo, type Rol, type Usuario } from "../api";

const MODULO_NOMBRE: Record<string, string> = {
  compras: "Compras",
  inventario: "Inventario",
  stock: "Stock",
  gastos: "Gastos",
  cartera: "Cartera",
  utilidad: "Utilidad",
  usuarios: "Usuarios",
};

/** "400: {"detail":"…"}" -> "…" */
function mensaje(e: unknown): string {
  const t = e instanceof Error ? e.message : String(e);
  const m = t.match(/^\d{3}: (.*)$/s);
  if (m) {
    try {
      return JSON.parse(m[1]).detail ?? t;
    } catch {
      return m[1];
    }
  }
  return t;
}

function fecha(iso: string | null): string {
  if (!iso) return "nunca";
  return new Date(iso).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Usuarios y roles. Solo la ve el rol dueño (el backend rechaza /api/usuarios
 * para los demás). Los roles son fijos y viven en acceso.py.
 *
 * Cambiar el rol, la contraseña o desactivar a alguien cierra sus sesiones
 * abiertas: la próxima petición de esa persona le pide entrar de nuevo.
 */
export default function UsuariosView({ yo }: { yo: string | null }) {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [roles, setRoles] = useState<Rol[]>([]);
  const [asignables, setAsignables] = useState<Modulo[]>([]);
  const [guardandoRol, setGuardandoRol] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  const [nuevo, setNuevo] = useState({ usuario: "", nombre: "", rol: "bodega", clave: "" });
  const [creando, setCreando] = useState(false);
  const [claveDe, setClaveDe] = useState<string | null>(null);
  const [claveNueva, setClaveNueva] = useState("");

  const cargar = () =>
    api
      .usuarios()
      .then((d) => {
        setUsuarios(d.usuarios);
        setRoles(d.roles);
        setAsignables(d.modulos_asignables);
      })
      .catch((e) => setError(mensaje(e)))
      .finally(() => setCargando(false));

  useEffect(() => {
    cargar();
  }, []);

  const rolNombre = (id: string) => roles.find((r) => r.id === id)?.nombre ?? id;

  async function alternarModulo(r: Rol, m: Modulo) {
    const modulos = r.modulos.includes(m) ? r.modulos.filter((x) => x !== m) : [...r.modulos, m];
    setError(null);
    setAviso(null);
    setGuardandoRol(r.id);
    // Se pinta de una vez; si el backend falla se recarga lo que quedó guardado.
    setRoles((rs) => rs.map((x) => (x.id === r.id ? { ...x, modulos } : x)));
    try {
      const res = await api.cambiarRol(r.id, modulos);
      setRoles((rs) => rs.map((x) => (x.id === r.id ? { ...x, modulos: res.modulos } : x)));
      setAviso(
        `${r.nombre}: ${MODULO_NOMBRE[m]} ${modulos.includes(m) ? "activado" : "desactivado"}. ` +
          "Aplica de inmediato; quien ya esté adentro ve las pestañas nuevas al recargar."
      );
    } catch (e) {
      setError(mensaje(e));
      await cargar();
    } finally {
      setGuardandoRol(null);
    }
  }

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setAviso(null);
    setCreando(true);
    try {
      const u = await api.crearUsuario(nuevo);
      setAviso(`Usuario "${u.usuario}" creado como ${rolNombre(u.rol)}. Compártele su contraseña en persona.`);
      setNuevo({ usuario: "", nombre: "", rol: nuevo.rol, clave: "" });
      await cargar();
    } catch (e) {
      setError(mensaje(e));
    } finally {
      setCreando(false);
    }
  }

  async function cambiar(u: Usuario, cambios: Parameters<typeof api.cambiarUsuario>[1], texto: string) {
    setError(null);
    setAviso(null);
    try {
      await api.cambiarUsuario(u.usuario, cambios);
      setAviso(texto);
      await cargar();
      return true;
    } catch (e) {
      setError(mensaje(e));
      return false;
    }
  }

  if (cargando) {
    return <p className="py-16 text-center text-sm text-sand-500">Cargando usuarios…</p>;
  }

  const input =
    "w-full rounded-lg border border-espresso-600 bg-espresso-950/60 px-3 py-2 text-sm text-sand-100 placeholder:text-sand-500/60 focus:border-amber focus:outline-none";

  return (
    <div className="grid gap-6">
      {/* Qué ve cada rol */}
      <section className="animate-rise grid gap-3 sm:grid-cols-3">
        {roles.map((r) => (
          <div key={r.id} className="rounded-2xl border border-espresso-700 bg-espresso-900/50 p-4 shadow-panel">
            <p className="font-display text-base font-semibold text-sand-50">{r.nombre}</p>
            <p className="mt-1 text-xs leading-relaxed text-sand-500">{r.ayuda}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {r.editable
                ? asignables.map((m) => {
                    const activo = r.modulos.includes(m);
                    return (
                      <button
                        key={m}
                        type="button"
                        role="switch"
                        aria-checked={activo}
                        disabled={guardandoRol === r.id}
                        onClick={() => alternarModulo(r, m)}
                        title={activo ? "Clic para quitarlo" : "Clic para darle acceso"}
                        className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition disabled:opacity-60 ${
                          activo
                            ? "border-amber/60 bg-amber/15 text-amber-bright"
                            : "border-espresso-600 text-sand-500 line-through decoration-sand-500/40 hover:border-amber/40 hover:text-sand-300"
                        }`}
                      >
                        {activo ? "✓ " : ""}
                        {MODULO_NOMBRE[m] ?? m}
                      </button>
                    );
                  })
                : r.modulos.map((m) => (
                    <span key={m} className="rounded-full border border-espresso-600 px-2 py-0.5 text-[10px] text-sand-300">
                      {MODULO_NOMBRE[m] ?? m}
                    </span>
                  ))}
            </div>
          </div>
        ))}
      </section>

      {/* Nuevo usuario */}
      <section className="animate-rise rounded-2xl border border-espresso-700 bg-espresso-900/50 p-5 shadow-panel [animation-delay:60ms]">
        <h2 className="font-display text-lg font-semibold text-sand-50">Nuevo usuario</h2>
        <form onSubmit={crear} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <input
            className={input}
            placeholder="usuario (ej. simon)"
            autoCapitalize="none"
            value={nuevo.usuario}
            onChange={(e) => setNuevo({ ...nuevo, usuario: e.target.value })}
          />
          <input
            className={input}
            placeholder="Nombre"
            value={nuevo.nombre}
            onChange={(e) => setNuevo({ ...nuevo, nombre: e.target.value })}
          />
          <select
            className={input}
            value={nuevo.rol}
            onChange={(e) => setNuevo({ ...nuevo, rol: e.target.value })}
          >
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.nombre}
              </option>
            ))}
          </select>
          <input
            className={input}
            type="password"
            autoComplete="new-password"
            placeholder="Contraseña (mín. 8)"
            value={nuevo.clave}
            onChange={(e) => setNuevo({ ...nuevo, clave: e.target.value })}
          />
          <button
            type="submit"
            disabled={creando || !nuevo.usuario.trim() || !nuevo.clave}
            className="rounded-lg bg-amber px-4 py-2 text-sm font-bold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-50"
          >
            {creando ? "Creando…" : "Crear"}
          </button>
        </form>
      </section>

      {error && (
        <p className="rounded-xl border border-pending/40 bg-pending/10 px-4 py-3 text-sm text-pending">{error}</p>
      )}
      {aviso && (
        <p className="rounded-xl border border-matched/40 bg-matched/10 px-4 py-3 text-sm text-matched">{aviso}</p>
      )}

      {/* Lista */}
      <section className="animate-rise overflow-hidden rounded-2xl border border-espresso-700 bg-espresso-900/50 shadow-panel [animation-delay:120ms]">
        <div className="border-b border-espresso-700 px-5 py-3">
          <h2 className="font-display text-lg font-semibold text-sand-50">Usuarios</h2>
          <p className="text-xs text-sand-500">
            Cambiar el rol o la contraseña, o desactivar, cierra las sesiones abiertas de esa persona.
          </p>
        </div>
        {usuarios.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-sand-500">
            Aún no hay usuarios. Mientras tanto se entra con el código maestro.
          </p>
        ) : (
          <ul>
            {usuarios.map((u) => {
              const soyYo = u.usuario === yo;
              return (
                <li
                  key={u.usuario}
                  className={`flex flex-wrap items-center gap-3 border-t border-dashed border-espresso-700 px-5 py-3 first:border-t-0 ${
                    u.activo ? "" : "opacity-50"
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sand-100">
                      {u.nombre}{" "}
                      <span className="font-mono text-xs text-sand-500">@{u.usuario}</span>
                      {soyYo && <span className="ml-2 text-[10px] text-amber">(tú)</span>}
                      {!u.activo && <span className="ml-2 text-[10px] text-pending">desactivado</span>}
                    </p>
                    <p className="text-[11px] text-sand-500">Último ingreso: {fecha(u.ultimo_ingreso)}</p>
                  </div>

                  <select
                    value={u.rol}
                    disabled={soyYo}
                    onChange={(e) =>
                      cambiar(u, { rol: e.target.value }, `${u.nombre} ahora es ${rolNombre(e.target.value)}.`)
                    }
                    className="rounded-lg border border-espresso-600 bg-espresso-950/60 px-2 py-1.5 text-xs text-sand-200 focus:border-amber focus:outline-none disabled:opacity-60"
                  >
                    {roles.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.nombre}
                      </option>
                    ))}
                  </select>

                  {claveDe === u.usuario ? (
                    <form
                      className="flex gap-2"
                      onSubmit={async (e) => {
                        e.preventDefault();
                        const ok = await cambiar(u, { clave: claveNueva }, `Contraseña de ${u.nombre} cambiada.`);
                        if (ok) {
                          setClaveDe(null);
                          setClaveNueva("");
                        }
                      }}
                    >
                      <input
                        type="password"
                        autoFocus
                        autoComplete="new-password"
                        placeholder="Nueva contraseña"
                        value={claveNueva}
                        onChange={(e) => setClaveNueva(e.target.value)}
                        className="w-40 rounded-lg border border-espresso-600 bg-espresso-950/60 px-2 py-1.5 text-xs text-sand-100 focus:border-amber focus:outline-none"
                      />
                      <button type="submit" className="rounded-lg bg-amber px-2.5 py-1.5 text-xs font-semibold text-espresso-950">
                        Guardar
                      </button>
                      <button
                        type="button"
                        onClick={() => setClaveDe(null)}
                        className="px-1 text-xs text-sand-500 hover:text-sand-300"
                      >
                        Cancelar
                      </button>
                    </form>
                  ) : (
                    <button
                      onClick={() => {
                        setClaveDe(u.usuario);
                        setClaveNueva("");
                      }}
                      className="rounded-lg border border-espresso-600 px-2.5 py-1.5 text-xs text-sand-300 transition hover:border-amber hover:text-amber"
                    >
                      Cambiar contraseña
                    </button>
                  )}

                  {!soyYo && (
                    <button
                      onClick={() =>
                        cambiar(
                          u,
                          { activo: !u.activo },
                          u.activo ? `${u.nombre} desactivado: ya no puede entrar.` : `${u.nombre} reactivado.`
                        )
                      }
                      className={`rounded-lg border px-2.5 py-1.5 text-xs transition ${
                        u.activo
                          ? "border-pending/40 text-pending hover:bg-pending/10"
                          : "border-matched/40 text-matched hover:bg-matched/10"
                      }`}
                    >
                      {u.activo ? "Desactivar" : "Reactivar"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <p className="text-center text-[11px] leading-relaxed text-sand-500/70">
        El código maestro (ACCESO_CODIGO) siempre entra como dueño: guárdalo aparte, es la llave para
        no quedar por fuera.
      </p>
    </div>
  );
}
