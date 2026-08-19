# Handoff — Motor de captura por foto + chat (reutilizable)

> Documento para llevar a Claude web: resume (1) el estado del proyecto Loggro y
> (2) cómo reutilizar el motor de "leer tirilla" + "chat por voz" en un proyecto nuevo.
> Decisiones tomadas: el proyecto nuevo usa **el mismo stack (Python/FastAPI + React/Vite)**
> y la estrategia de reúso es **copiar el núcleo** (extraer a paquete más adelante).

---

## 1. Estado del proyecto actual (Loggro asistente IA)

App para registrar **compras** y **gastos** en Loggro Restobar (API `api.pirpos.com`).
Flujo: foto de tirilla **o** chat con voz → extraer con IA (Gemini) → homologar producto
→ registrar movimiento/gasto en Loggro.

- **Backend:** FastAPI (`backend/app.py`), desplegado en Vercel como función ASGI (`api/index.py`).
- **Frontend:** React + Vite + Tailwind (`frontend/`).
- **IA:** Google Gemini (free tier), `gemini-2.5-flash`. Requiere `GEMINI_API_KEY`.
- **Homologación (mapa descripción→producto):** se persiste en **Redis** (en Vercel el
  filesystem es de solo lectura).

### Fix reciente (importante para no repetir)
La integración de Redis de Vercel expone **`REDIS_URL`** (cadena `rediss://...`),
NO la API REST `KV_REST_API_*`. El almacén (`homologacion_store.py`) ahora resuelve en
este orden: 1) `REDIS_URL`/`KV_URL` (cliente `redis-py`), 2) KV REST, 3) archivo local (dev).
Síntoma del bug que causó: al homologar "el tap no seleccionaba" (el guardado daba 500 al
escribir en FS de solo lectura y el frontend lo tragaba). Para sembrar un Redis nuevo:
`python seed_kv.py`.

---

## 2. El núcleo reutilizable (ya está desacoplado)

La funcionalidad de **foto→datos** y **chat→datos** está construida como **motor genérico
+ "presets"**. Factura y gasto son solo dos presets del mismo motor. Nada de esto depende
de Loggro ni de FastAPI.

### 2.1 Backend — paquete `loggro_intake/` (Python puro, solo depende de `requests`)

| Archivo | Función pública | Contrato |
|---|---|---|
| `gemini.py`   | `generar_json(parts, schema, model=None, max_tokens=8192) -> dict` | Llama a Gemini con `parts` (texto y/o imagen) y un `responseSchema`; devuelve el dict ya validado. Reintenta 5xx/429, desactiva "thinking". |
| `extractor.py`| `extraer_imagen(image_bytes, schema, prompt, media_type="image/jpeg") -> dict` | **Genérico:** imagen → JSON según cualquier `schema`. |
| `chat.py`     | `conversar_doc(mensaje, doc_schema, system_prompt, estado=None, historial=None, etiqueta_doc="DOCUMENTO") -> {"data":..., "respuesta":...}` | **Genérico:** un turno de chat con estado que construye/actualiza un documento. |
| `schema.py`   | `FACTURA_SCHEMA`, `media_type_from_name(name)` | Preset de factura + helper. |
| (presets)     | `extraer_tirilla`, `conversar` (factura); `gasto.py`: `extraer_gasto`, `conversar_gasto` | Ejemplos de cómo montar un preset sobre el núcleo. |

**Variables de entorno:** `GEMINI_API_KEY` (obligatoria), `LOGGRO_EXTRACTOR_MODEL`
(opcional; default `gemini-2.5-flash`).

**Detalle clave de Gemini:** el `responseSchema` es un subconjunto de OpenAPI — **NO admite
`additionalProperties`**. Define todos los campos en `properties` y lista los obligatorios
en `required`.

### 2.2 Frontend — componentes genéricos (TypeScript generics)

| Componente | Props clave | Qué trae gratis |
|---|---|---|
| `ImagenUpload<R>` | `extraer: (file: File) => Promise<R>`, `onResult: (r: R) => void`, `etiqueta?` | Drag & drop, preview, **cámara/galería** (`accept="image/*"`), estados de carga/error. |
| `ChatCaptura<E, R>` | `enviar: (mensaje, estado, historial) => Promise<{estado, respuesta, result}>`, `onResult`, `placeholder?`, `sugerencias?`, `resumen?` | Burbujas de chat, **dictado por voz** (Web Speech API `es-CO`), manejo de historial/estado. |

Solo dependen del tipo trivial `ChatTurn = { role: "user"|"assistant"; content: string }`
y de las clases Tailwind del tema (ver `tailwind.config.js`: colores `espresso/amber/sand`).

---

## 3. Receta para el proyecto NUEVO (copiar, mismo stack)

### Paso 0 — Estructura
Copiar del proyecto actual al nuevo:
```
loggro_intake/            -> intake/            (renombrar libre; es el núcleo)
  gemini.py               (sin cambios)
  extractor.py            (sin cambios)
  chat.py                 (sin cambios)
  schema.py               (reemplazar por tu preset)
frontend/src/components/
  ImagenUpload.tsx        (sin cambios)
  ChatCaptura.tsx         (sin cambios)
tailwind.config.js        (copiar el tema, o adaptar las clases)
```
Dependencias backend: `fastapi`, `uvicorn`, `requests`, `python-multipart`,
`python-dotenv` (+ `redis` si vas a persistir algo).

### Paso 1 — Definir tu preset (lo único nuevo del backend)
Crea el esquema y los prompts de TU documento. Ejemplo plantilla:

```python
# intake/mi_doc.py
from .extractor import extraer_imagen
from .chat import conversar_doc
from .gemini import generar_json  # si lo necesitas directo

MI_SCHEMA = {
    "type": "object",
    "properties": {
        # ...tus campos... (recuerda: SIN additionalProperties)
    },
    "required": [ ... ],
}

PROMPT_IMG = """Eres un experto en leer <TU DOCUMENTO>. Extrae al esquema JSON. Reglas: ..."""
SYSTEM_CHAT = """Eres un asistente que arma <TU DOCUMENTO> conversando. Recibes el ESTADO
ACTUAL (JSON) y el MENSAJE nuevo; devuelves el documento completo actualizado + respuesta breve."""

def extraer_mi_doc(image_bytes, media_type="image/jpeg"):
    return extraer_imagen(image_bytes, MI_SCHEMA, PROMPT_IMG, media_type)

def conversar_mi_doc(mensaje, estado=None, historial=None):
    out = conversar_doc(mensaje, MI_SCHEMA, SYSTEM_CHAT, estado=estado,
                        historial=historial, etiqueta_doc="MI DOC")
    return {"data": out.get("data"), "respuesta": out.get("respuesta", "")}
```

### Paso 2 — Endpoints FastAPI (2 endpoints, mismo patrón que `backend/app.py`)
```python
@app.post("/api/extraer")
async def extraer(file: UploadFile = File(...)):
    data = await file.read()
    media = media_type_from_name(file.filename or "doc.jpg")
    return {"data": extraer_mi_doc(data, media)}

@app.post("/api/chat")
def chat(req: ChatRequest):   # {mensaje, estado, historial}
    out = conversar_mi_doc(req.mensaje, estado=req.estado,
                           historial=[t.model_dump() for t in req.historial])
    return out
```

### Paso 3 — Frontend: cablear los componentes ( no se tocan por dentro)
```tsx
// Foto
<ImagenUpload
  extraer={(file) => api.extraer(file)}     // POST /api/extraer (FormData)
  onResult={(r) => setDatos(r.data)}
  etiqueta="Toca para tomar/subir la foto"
/>

// Chat con voz
<ChatCaptura
  placeholder="Dicta o escribe…"
  sugerencias={["ejemplo 1", "ejemplo 2"]}
  enviar={async (mensaje, estado, historial) => {
    const r = await api.chat({ mensaje, estado, historial });
    return { estado: r.data, respuesta: r.respuesta, result: r };
  }}
  onResult={(r) => setDatos(r.data)}
  resumen={(e) => e ? `…resumen del estado…` : null}
/>
```

### Paso 4 — Deploy en Vercel (igual que ahora)
- `vercel.json`: build del frontend + función `api/index.py` (expone `app` ASGI).
- Rewrite `/api/(.*)` → `/api/index`.
- **FS de solo lectura:** cualquier persistencia va a Redis (`REDIS_URL`), no a archivos.
- Env vars en Vercel: `GEMINI_API_KEY` (+ las que tu proyecto necesite).

---

## 4. Qué cambiar vs. qué NO tocar

**NO tocar (copiar tal cual):** `gemini.py`, `extractor.py`, `chat.py`,
`ImagenUpload.tsx`, `ChatCaptura.tsx`.

**Sí cambiar (lo propio de tu proyecto):** el esquema + prompts (preset), los 2 endpoints,
la capa `api.ts` del front, la pantalla que orquesta, y la lógica de negocio posterior
(lo que hagas con el JSON extraído).

---

## 5. Roadmap a "paquete compartido" (cuando se estabilice)
1. Mover el núcleo (`gemini/extractor/chat`) a un repo propio, p.ej. `ai-doc-intake`,
   con nombre genérico (sin "loggro").
2. Publicarlo como paquete: Python `pip install git+https://github.com/.../ai-doc-intake`.
3. Los componentes React: pequeña lib npm propia o carpeta compartida `@tu-org/intake-ui`.
4. Ambos proyectos pasan de "copia" a "dependencia" → una sola fuente de verdad.
