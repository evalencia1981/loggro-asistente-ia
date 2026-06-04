import { useRef, useState } from "react";

interface Props<R> {
  extraer: (file: File) => Promise<R>;
  onResult: (r: R) => void;
  etiqueta?: string; // texto del dropzone
}

// Subida de imagen + extracción con IA. Genérico: recibe la función `extraer`
// (foto -> datos) y entrega el resultado al padre. Reutilizable (factura, gasto…).
export default function ImagenUpload<R>({ extraer, onResult, etiqueta }: Props<R>) {
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const choose = (f: File | null) => {
    setError(null);
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setError("El archivo debe ser una imagen (JPG, PNG…).");
      return;
    }
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const run = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      onResult(await extraer(file));
    } catch (e) {
      setError(`No se pudo extraer: ${e}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          choose(e.dataTransfer.files?.[0] ?? null);
        }}
        onClick={() => inputRef.current?.click()}
        className={`group relative flex cursor-pointer flex-col items-center justify-center overflow-hidden rounded-xl border-2 border-dashed px-4 py-6 text-center transition ${
          drag
            ? "border-amber bg-amber/10"
            : "border-espresso-600 bg-espresso-950/50 hover:border-amber/60 hover:bg-espresso-900/60"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => choose(e.target.files?.[0] ?? null)}
        />
        {preview ? (
          <img
            src={preview}
            alt="documento"
            className="max-h-44 w-auto rounded-lg border border-espresso-700 object-contain shadow-panel"
          />
        ) : (
          <>
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-amber/15 text-amber">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M14 3v4a1 1 0 0 0 1 1h4" />
                <path d="M5 21V5a2 2 0 0 1 2-2h8l5 5v13a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2Z" />
                <path d="M12 11v6M9 14h6" />
              </svg>
            </span>
            <p className="mt-2 text-sm font-medium text-sand-100">
              {etiqueta ?? "Toca para tomar/subir la foto"}
            </p>
            <p className="mt-0.5 text-xs text-sand-500">o arrástrala aquí · JPG, PNG</p>
          </>
        )}
      </div>

      {preview && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            onClick={run}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-xl bg-amber px-5 py-2.5 text-sm font-semibold text-espresso-950 transition hover:bg-amber-bright disabled:opacity-60"
          >
            {loading ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-espresso-950/30 border-t-espresso-950" />
                Leyendo…
              </>
            ) : (
              "Extraer con IA"
            )}
          </button>
          <button
            onClick={() => {
              setFile(null);
              setPreview(null);
              setError(null);
            }}
            className="text-sm text-sand-400 underline-offset-4 transition hover:text-amber hover:underline"
          >
            Cambiar imagen
          </button>
        </div>
      )}

      {error && (
        <p className="mt-3 rounded-lg border border-pending/40 bg-pending/10 px-3 py-2 text-sm text-pending">
          {error}
        </p>
      )}
    </div>
  );
}
