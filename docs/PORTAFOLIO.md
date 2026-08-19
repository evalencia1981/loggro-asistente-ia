# Loggro Asistente IA — Ficha de portafolio

## 1. Pitch corto
Asistente con IA que captura compras de un restobar desde una foto o por voz, homologa los productos contra el catálogo real y los registra en Loggro.

## 2. Descripción media
Loggro Asistente IA conecta la operación diaria de un restobar con su sistema de inventario (Loggro / api.pirpos.com) sin digitar a mano. El usuario sube la foto de una tirilla o dicta la factura en lenguaje natural: la IA (Google Gemini) extrae proveedor, ítems y totales en JSON estructurado, y la app los empareja con los productos reales del catálogo.

La homologación **aprende por NIT del proveedor**, así que proveedores duplicados que comparten NIT reutilizan lo ya aprendido, e incluso reconoce descripciones que traen el código consecutivo del proveedor. Aplica factor de empaque (un six pack = 6 unidades, convirtiendo cantidad y costo unitario) y permite registrar o deshacer la compra en Loggro con un clic. El núcleo de captura (foto→JSON, chat→JSON) está desacoplado como paquete reutilizable para otros proyectos.

## 3. Características
- 📸 Captura por foto: la IA lee la tirilla y extrae proveedor, ítems y totales.
- 🎙️ Captura por chat/voz: dictas o escribes la factura y se arma sola (Web Speech API, es-CO).
- 🧠 Homologación que aprende por NIT del proveedor y reconoce códigos consecutivos.
- 📦 Factor de empaque automático: convierte cantidad y costo unitario (ej. six pack = 6).
- ↩️ Registrar y deshacer la compra en Loggro (`POST`/`DELETE /inventories`).
- 🔌 Motor de captura IA reutilizable (`loggro_intake`) independiente de Loggro y FastAPI.

## 4. Stack técnico
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS.
- **Backend:** Python + FastAPI (función ASGI), cliente propio de la API de Loggro.
- **IA / servicios:** Google Gemini (`gemini-2.5-flash`) con salida JSON estructurada; Web Speech API para dictado.
- **Datos / persistencia:** Redis (homologación aprendida; `REDIS_URL`/KV), con fallback a archivo local en desarrollo.
- **Deploy:** Vercel (build del frontend + `api/index.py` como función ASGI).

## 5. Metadatos
- **Nombre:** Loggro Asistente IA
- **Categoría:** SaaS · Inventario / Restaurantes · IA
- **Estado:** MVP
- **Mi rol:** Desarrollador full-stack (diseño, backend, frontend e integración con IA)
- **Año:** 2026
