// Tarjeta de portafolio reutilizable. Soporta dark mode vía Tailwind.
// Datos de Loggro Asistente IA precargados al final como ejemplo de uso.

export function PortfolioCard({
  nombre,
  categoria,
  estado = "MVP",
  descripcion,
  features = [],
  stack = [],
  demo,
  codigo,
}) {
  return (
    <article className="group flex flex-col rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:shadow-md dark:border-slate-700 dark:bg-slate-900">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-xl font-semibold text-slate-900 dark:text-white">{nombre}</h3>
          <p className="text-sm text-indigo-600 dark:text-indigo-400">{categoria}</p>
        </div>
        <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
          {estado}
        </span>
      </header>

      <p className="mt-4 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        {descripcion}
      </p>

      <ul className="mt-4 space-y-1.5 text-sm text-slate-600 dark:text-slate-300">
        {features.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>

      <div className="mt-5 flex flex-wrap gap-2">
        {stack.map((t) => (
          <span
            key={t}
            className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
          >
            {t}
          </span>
        ))}
      </div>

      {(demo || codigo) && (
        <div className="mt-5 flex gap-4 text-sm font-medium">
          {demo && (
            <a href={demo} className="text-indigo-600 hover:underline dark:text-indigo-400">
              Demo
            </a>
          )}
          {codigo && (
            <a href={codigo} className="text-slate-500 hover:underline dark:text-slate-400">
              Código
            </a>
          )}
        </div>
      )}
    </article>
  );
}

// Ejemplo de uso con los datos de este proyecto:
export function LoggroAsistenteCard() {
  return (
    <PortfolioCard
      nombre="Loggro Asistente IA"
      categoria="SaaS · Inventario / Restaurantes · IA"
      estado="MVP"
      descripcion="Asistente con IA que captura compras de un restobar desde una foto o por voz, extrae proveedor, ítems y totales con Google Gemini, y los homologa contra el catálogo real para registrarlos en Loggro. La homologación aprende por NIT del proveedor y aplica factor de empaque automáticamente."
      features={[
        "📸 Captura por foto: la IA lee la tirilla y extrae proveedor, ítems y totales",
        "🎙️ Captura por chat/voz con dictado (Web Speech API, es-CO)",
        "🧠 Homologación que aprende por NIT del proveedor",
        "📦 Factor de empaque automático (ej. six pack = 6 unidades)",
        "↩️ Registrar y deshacer la compra en Loggro",
        "🔌 Motor de captura IA reutilizable e independiente",
      ]}
      stack={["React", "TypeScript", "Vite", "Tailwind", "FastAPI", "Google Gemini", "Redis", "Vercel"]}
    />
  );
}
