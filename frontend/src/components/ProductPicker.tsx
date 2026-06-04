import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type Product } from "../api";

interface Props {
  onPick: (p: Product) => void;
  autoFocus?: boolean;
  placeholder?: string;
}

interface Coords {
  top: number;
  left: number;
  width: number;
  maxHeight: number;
}

// Combobox con búsqueda en vivo contra el catálogo real de Loggro.
// El desplegable se renderiza en un portal con position:fixed para que NO quede
// atrapado por los contextos de apilamiento de las filas animadas (si no, las
// filas siguientes lo taparían y no se podría hacer clic).
export default function ProductPicker({ onPick, autoFocus, placeholder }: Props) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Product[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const [coords, setCoords] = useState<Coords | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    const t = setTimeout(() => {
      api
        .searchProducts(q.trim(), 30)
        .then((r) => {
          setResults(r);
          setActive(0);
          setOpen(true);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  // Posiciona el portal bajo el input; se reubica al hacer scroll o redimensionar.
  const updateCoords = () => {
    const el = boxRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const gap = 8;
    const below = window.innerHeight - r.bottom - gap - 8;
    setCoords({
      top: r.bottom + gap,
      left: r.left,
      width: r.width,
      maxHeight: Math.max(160, Math.min(288, below)),
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    updateCoords();
    window.addEventListener("scroll", updateCoords, true);
    window.addEventListener("resize", updateCoords);
    return () => {
      window.removeEventListener("scroll", updateCoords, true);
      window.removeEventListener("resize", updateCoords);
    };
  }, [open, results.length]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (boxRef.current?.contains(t)) return;
      if (listRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const pick = (p: Product) => {
    onPick(p);
    setQ("");
    setResults([]);
    setOpen(false);
  };

  const panelStyle = coords
    ? {
        top: coords.top,
        left: coords.left,
        width: coords.width,
        maxHeight: coords.maxHeight,
      }
    : undefined;

  return (
    <div className="relative">
      <div
        ref={boxRef}
        className="flex items-center gap-2 rounded-xl border border-espresso-600 bg-espresso-900/70 px-3 py-2 transition focus-within:border-amber focus-within:shadow-glow"
      >
        <svg
          className="h-4 w-4 shrink-0 text-sand-500"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          autoFocus={autoFocus}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, results.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter" && results[active]) {
              e.preventDefault();
              pick(results[active]);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          placeholder={placeholder ?? "Buscar producto en Loggro…"}
          className="w-full bg-transparent text-sm text-sand-50 placeholder:text-sand-500/70 focus:outline-none"
        />
        {loading && (
          <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-amber/30 border-t-amber" />
        )}
      </div>

      {open &&
        results.length > 0 &&
        coords &&
        createPortal(
          <ul
            ref={listRef as React.RefObject<HTMLUListElement>}
            style={panelStyle}
            className="fixed z-[100] overflow-auto rounded-xl border border-espresso-600 bg-espresso-850 py-1 shadow-panel animate-fade"
          >
            {results.map((p, i) => (
              <li key={p.id}>
                <button
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(p)}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition ${
                    i === active ? "bg-amber/15 text-sand-50" : "text-sand-100 hover:bg-espresso-800"
                  }`}
                >
                  <span className="truncate">{p.name}</span>
                  <span className="shrink-0 font-mono text-[10px] text-sand-500">
                    {p.id.slice(-6)}
                  </span>
                </button>
              </li>
            ))}
          </ul>,
          document.body
        )}

      {open &&
        !loading &&
        q.trim() &&
        results.length === 0 &&
        coords &&
        createPortal(
          <div
            ref={listRef}
            style={panelStyle ? { top: coords.top, left: coords.left, width: coords.width } : undefined}
            className="fixed z-[100] rounded-xl border border-espresso-600 bg-espresso-850 px-3 py-3 text-sm text-sand-500 shadow-panel"
          >
            Sin coincidencias para “{q}”.
          </div>,
          document.body
        )}
    </div>
  );
}
