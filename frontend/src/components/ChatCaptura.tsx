import { useEffect, useRef, useState } from "react";
import { type ChatTurn } from "../api";

// Resultado de un turno: el nuevo estado del documento + la respuesta del asistente
// + el objeto crudo de la API (que se pasa al onResult del padre).
export interface TurnoChat<E, R> {
  estado: E;
  respuesta: string;
  result: R;
}

interface Props<E, R> {
  placeholder?: string;
  sugerencias?: string[];
  enviar: (mensaje: string, estado: E | null, historial: ChatTurn[]) => Promise<TurnoChat<E, R>>;
  onResult: (result: R) => void;
  resumen?: (estado: E | null) => string | null; // línea de estado (ej. "2 ítems")
}

function getSpeechRecognition(): any {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

// Chat conversacional reutilizable con dictado por voz (Web Speech API).
export default function ChatCaptura<E, R>({
  placeholder,
  sugerencias = [],
  enviar,
  onResult,
  resumen,
}: Props<E, R>) {
  const [messages, setMessages] = useState<ChatTurn[]>([]);
  const [estado, setEstado] = useState<E | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const accumRef = useRef("");
  const liveRef = useRef("");
  const wantRef = useRef(false);

  const speechSupported = !!getSpeechRecognition();

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    return () => {
      wantRef.current = false;
      try {
        recognitionRef.current?.stop();
      } catch {
        /* noop */
      }
    };
  }, []);

  const startRecognition = () => {
    const SR = getSpeechRecognition();
    if (!SR) return;
    const rec = new SR();
    rec.lang = "es-CO";
    rec.interimResults = true;
    rec.continuous = true;
    rec.onresult = (e: any) => {
      let session = "";
      for (let i = 0; i < e.results.length; i++) session += e.results[i][0].transcript;
      const text = (accumRef.current ? accumRef.current + " " : "") + session;
      liveRef.current = text;
      setInput(text);
    };
    rec.onerror = (e: any) => {
      if (e?.error === "not-allowed" || e?.error === "service-not-allowed") {
        wantRef.current = false;
        setListening(false);
      }
    };
    rec.onend = () => {
      if (wantRef.current) {
        accumRef.current = liveRef.current;
        try {
          rec.start();
        } catch {
          wantRef.current = false;
          setListening(false);
        }
      } else {
        setListening(false);
      }
    };
    recognitionRef.current = rec;
    rec.start();
  };

  const stopMic = () => {
    wantRef.current = false;
    try {
      recognitionRef.current?.stop();
    } catch {
      /* noop */
    }
    setListening(false);
  };

  const toggleMic = () => {
    if (listening) {
      stopMic();
      return;
    }
    if (!getSpeechRecognition()) return;
    accumRef.current = input.trim();
    liveRef.current = input.trim();
    wantRef.current = true;
    setListening(true);
    startRecognition();
  };

  const send = async (texto?: string) => {
    const mensaje = (texto ?? input).trim();
    if (!mensaje || loading) return;
    if (listening) stopMic();
    setError(null);
    setInput("");
    const nuevoHistorial: ChatTurn[] = [...messages, { role: "user", content: mensaje }];
    setMessages(nuevoHistorial);
    setLoading(true);
    try {
      const r = await enviar(mensaje, estado, messages);
      setEstado(r.estado);
      setMessages([...nuevoHistorial, { role: "assistant", content: r.respuesta }]);
      onResult(r.result);
    } catch (e) {
      setError(`No se pudo procesar: ${e}`);
      setMessages([
        ...nuevoHistorial,
        { role: "assistant", content: "Ups, hubo un error al procesar. Intenta de nuevo." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const linea = resumen?.(estado) ?? null;

  return (
    <div className="flex flex-col rounded-xl border border-espresso-600 bg-espresso-950/40">
      <div ref={scrollRef} className="max-h-72 min-h-[140px] overflow-y-auto p-3">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-amber/15 text-amber">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />
              </svg>
            </span>
            <p className="text-sm text-sand-200">Dicta o escribe</p>
            <div className="flex flex-wrap justify-center gap-1.5">
              {sugerencias.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-espresso-600 bg-espresso-900/60 px-2.5 py-1 text-[11px] text-sand-400 transition hover:border-amber hover:text-amber"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {messages.map((m, i) => (
              <li key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <span
                  className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
                    m.role === "user"
                      ? "rounded-br-sm bg-amber text-espresso-950"
                      : "rounded-bl-sm bg-espresso-800 text-sand-100"
                  }`}
                >
                  {m.content}
                </span>
              </li>
            ))}
            {loading && (
              <li className="flex justify-start">
                <span className="inline-flex items-center gap-1.5 rounded-2xl rounded-bl-sm bg-espresso-800 px-3 py-2 text-sm text-sand-400">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sand-400 [animation-delay:0ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sand-400 [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-sand-400 [animation-delay:300ms]" />
                </span>
              </li>
            )}
          </ul>
        )}
      </div>

      {linea && (
        <div className="border-t border-espresso-700 px-3 py-1.5 text-[11px] text-sand-500">{linea}</div>
      )}

      <div className="flex items-end gap-2 border-t border-espresso-700 p-2">
        {speechSupported && (
          <button
            onClick={toggleMic}
            title={listening ? "Detener dictado" : "Dictar por voz"}
            className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg border transition ${
              listening
                ? "animate-pulse border-pending bg-pending/20 text-pending"
                : "border-espresso-600 bg-espresso-900/60 text-sand-400 hover:border-amber hover:text-amber"
            }`}
          >
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
              <path d="M19 10a7 7 0 0 1-14 0M12 17v4" />
            </svg>
          </button>
        )}
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          rows={1}
          placeholder={listening ? "Escuchando…" : placeholder ?? "Escribe o dicta…"}
          className="max-h-28 min-h-[36px] w-full resize-y rounded-lg border border-espresso-600 bg-espresso-900/60 px-3 py-2 text-sm text-sand-50 outline-none transition placeholder:text-sand-500/70 focus:border-amber focus:shadow-glow"
        />
        <button
          onClick={() => send()}
          disabled={loading || !input.trim()}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-amber text-espresso-950 transition hover:bg-amber-bright disabled:opacity-50"
          title="Enviar"
        >
          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      </div>

      {error && (
        <p className="border-t border-pending/30 bg-pending/10 px-3 py-2 text-sm text-pending">{error}</p>
      )}
    </div>
  );
}
