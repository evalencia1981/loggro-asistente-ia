# loggro-asistente-ia

Asistente con IA para **Loggro / Restobar** (api.pirpos.com). Captura **compras** (y pronto **gastos**) desde una **foto** o por **chat/voz**, homologa los productos contra el catálogo real y los registra en Loggro. La autenticación es la misma para todos los módulos.

## Qué hace

- **Captura por foto:** subes la tirilla/factura y la IA (Google Gemini) extrae proveedor, ítems, totales.
- **Captura por chat/voz:** dictas o escribes la factura en lenguaje natural y se arma sola (Web Speech API para el dictado).
- **Homologación que aprende:** empareja la descripción de la tirilla con el producto de Loggro. Se aprende **por NIT del proveedor** (proveedores duplicados con el mismo NIT comparten lo aprendido) y reconoce aunque la descripción traiga el código consecutivo del proveedor.
- **Factor de empaque:** un six pack = 6 unidades; al registrar convierte cantidad y costo unitario.
- **Registrar / deshacer** la compra en Loggro (`POST /inventories`, `DELETE /inventories/{id}`).

## Arquitectura

```
loggro-asistente-ia/
├─ loggro_client.py        # Cliente de la API de Loggro (login, inventario, proveedores…)
├─ homologacion_store.py   # Almacén de homologación (por NIT + descripción, con factor)
├─ homologacion.json       # Datos aprendidos
├─ loggro_intake/          # Paquete reutilizable de captura con IA (Gemini)
│  ├─ gemini.py            #   motor: JSON estructurado + reintentos
│  ├─ extractor.py         #   imagen → datos
│  └─ chat.py              #   lenguaje natural → datos
├─ backend/app.py          # API FastAPI (reutiliza loggro_client + loggro_intake)
└─ frontend/               # UI React + TypeScript + Vite + Tailwind
```

## Requisitos y configuración

- Python 3, Node 18+.
- Archivo `.env` en la raíz (NO se sube a Git):

```
LOGGRO_BASE_URL=https://api.pirpos.com
LOGGRO_EMAIL=tu_correo
LOGGRO_PASSWORD=tu_clave
GEMINI_API_KEY=tu_api_key      # gratis en https://aistudio.google.com/app/apikey
# LOGGRO_EXTRACTOR_MODEL=gemini-2.5-flash   # opcional
```

## Cómo correr

**Opción rápida (Windows):** doble clic en `start.bat` → levanta backend + frontend + túnel HTTPS e imprime la URL pública. `stop.bat` detiene todo.

**Manual (dos terminales):**
```powershell
# 1) Backend (desde la raíz)
python -X utf8 -m uvicorn backend.app:app --reload --port 8090
# 2) Frontend
cd frontend
npm install   # solo la primera vez
npm run dev
```
Abre **http://localhost:8091**.

Los puertos de este proyecto son **8090 (API)** y **8091 (web)**, definidos en
`ports.json` (los leen `start.ps1`, `stop.ps1` y `vite.config.ts`). El reparto de
puertos entre proyectos está en [docs/PUERTOS.md](docs/PUERTOS.md).

## Flujo de uso

1. **Captura** la factura: sube la foto o usa el chat/voz (o pega los ítems a mano).
2. Elige el **proveedor** (se sugiere por NIT si está registrado).
3. **Analiza** → ves qué está reconocido y qué falta homologar.
4. Homologa los pendientes (con su factor de empaque si aplica). Queda aprendido.
5. **Registrar compra en Loggro** (con confirmación). Puedes **deshacer** si fue prueba.

## Próximos pasos

- Módulo de **Gastos** (`/expenses`: crear, listar, eliminar) reutilizando foto + chat.
- Separar `loggro_intake` como librería independiente para otros proyectos.
- Migrar `homologacion.json` a base de datos cuando crezca.
