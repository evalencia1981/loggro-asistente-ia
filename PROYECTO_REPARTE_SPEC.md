# Proyecto nuevo — "Reparte" (split de cuentas + finanzas personales con IA)

> Spec inicial para planear en Claude web. Nombre de trabajo: **Reparte** (renombrable).
> Reutiliza el motor de captura por **foto** y **chat por voz** del proyecto Loggro
> (ver `HANDOFF_INTAKE.md`).

## Decisiones tomadas
- **Stack:** FastAPI (Python) + React/Vite + Tailwind (igual que Loggro). Reúso por **copia** del núcleo.
- **Usuarios:** **híbrido** — un *dueño* con cuenta crea/gestiona el grupo; los *invitados* participan como nombres, sin registrarse (con link compartible).
- **Persistencia:** **Postgres** (Neon o Supabase, free tier). Dominio relacional + historial + balances.
- **MVP:** las **dos** funcionalidades desde el inicio (repartir cuenta + gastos personales).

---

## 1. Concepto
Tipo Tricount, pero con IA:
1. **Repartir una cuenta** (restaurante/evento): subes la **foto de la factura** → reconoce los
   productos → decides el reparto: **equitativo** (todos por igual) o **por producto** (cada ítem
   se asigna a quien lo consumió; los compartidos —p.ej. el pastel de la cumpleañera— se dividen
   entre varios). Resultado: **quién le debe a quién** y cuánto.
2. **Finanzas personales** (privado del dueño): registrar gastos por **voz o texto**
   ("me gasté 100.000 en el bar") → categorización + resúmenes.

Los dos flujos comparten el mismo motor de captura (foto→JSON, chat→JSON).

---

## 2. Cómo encaja el motor reutilizable (3 presets)
| Preset | Motor que reúsa | Entrada | Salida |
|---|---|---|---|
| **A. Factura → ítems** | `extraer_imagen(bytes, schema, prompt)` | Foto de la cuenta | Lista de ítems + totales/impuestos/propina |
| **B. Asignación por chat** | `conversar_doc(msg, schema, system, estado)` | Voz/texto: *"la pizza fue de Juan; el pastel se reparte entre todos"* + estado (ítems+comensales) | Ítems con `asignado_a: [nombres]` actualizado |
| **C. Gasto personal** | `conversar_doc` / `extraer_imagen` | Voz/texto o foto | `{monto, categoria, descripcion, fecha, medio_pago}` |

**Clave del preset B:** al chat se le pasa en el `estado` la lista de comensales y de ítems, y
él devuelve la asignación. Es exactamente para lo que sirve `conversar_doc` (estado + lenguaje
natural → JSON). Reúso directo, sin tocar el motor.

### Esquemas (compatibles con Gemini: SIN `additionalProperties`)

**A — Factura:**
```python
CUENTA_SCHEMA = {
  "type": "object",
  "properties": {
    "comercio": {"type": "string"},
    "fecha": {"type": "string"},
    "items": {"type": "array", "items": {
      "type": "object",
      "properties": {
        "descripcion": {"type": "string"},
        "cantidad": {"type": "number"},
        "precio_unitario": {"type": "number"},
        "total_linea": {"type": "number"}
      },
      "required": ["descripcion", "cantidad", "total_linea"]
    }},
    "subtotal": {"type": "number"},
    "impuestos": {"type": "number"},
    "propina": {"type": "number"},
    "total": {"type": "number"}
  },
  "required": ["items", "total"]
}
```

**B — Asignación (estado que entra y sale del chat):**
```python
ASIGNACION_SCHEMA = {
  "type": "object",
  "properties": {
    "items": {"type": "array", "items": {
      "type": "object",
      "properties": {
        "descripcion": {"type": "string"},
        "total_linea": {"type": "number"},
        "compartido_entre_todos": {"type": "boolean"},
        "asignado_a": {"type": "array", "items": {"type": "string"}}  # nombres de comensales
      },
      "required": ["descripcion", "total_linea", "asignado_a"]
    }}
  },
  "required": ["items"]
}
# system prompt incluye: lista de comensales válidos + reglas (compartido => dividir entre asignados;
# si dice "entre todos" => compartido_entre_todos=true).
```

**C — Gasto personal:** reúsa el `GASTO_SCHEMA` existente, adaptado:
`{monto, categoria, descripcion, fecha, medio_pago}`.

---

## 3. Modelo de datos (Postgres)

```
users           # dueños registrados (auth)
  id, email, name, created_at

groups          # cada cuenta compartida / evento
  id, owner_id -> users, name, currency='COP', share_token, created_at

participants    # personas dentro de un grupo (comensales)
  id, group_id -> groups, name, user_id -> users NULL  # NULL si es solo un nombre

expenses        # una factura/gasto del grupo
  id, group_id, payer_id -> participants, title, date,
  subtotal, taxes, tip, total, split_mode ('equal'|'by_item'),
  source ('photo'|'manual'|'chat'), created_at

expense_items   # líneas de la factura (del preset A)
  id, expense_id, description, qty, line_total, shared_all (bool)

item_shares     # qué participante consume cada ítem (del preset B / UI)
  id, item_id -> expense_items, participant_id -> participants, weight=1

settlements     # pagos registrados para saldar deudas
  id, group_id, from_id -> participants, to_id -> participants, amount, date

personal_expenses  # finanzas personales (privadas del dueño)
  id, user_id -> users, amount, category, description, date, source
```

**Notas de reparto:**
- `split_mode='equal'`: el `total` se divide entre todos los participants del grupo (o los marcados).
- `split_mode='by_item'`: cada `expense_item` se reparte entre sus `item_shares` (o entre todos si
  `shared_all`). **Impuestos y propina** se prorratean según el subtotal consumido por cada persona.

---

## 4. Algoritmo: "quién le debe a quién"
1. Por cada participante calcular **balance neto** = (lo que pagó) − (lo que consumió/le toca).
2. Acreedores (balance > 0) y deudores (balance < 0).
3. **Minimizar transacciones** (greedy): emparejar el mayor deudor con el mayor acreedor,
   transferir `min(|deudor|, acreedor)`, repetir hasta saldar.
4. Mostrar la lista mínima de pagos: "Ana → Carlos: $X".
```
def liquidar(balances):  # {nombre: neto}
    deudores  = sorted([(n,-v) for n,v in balances.items() if v < -0.5])
    acreedores= sorted([(n, v) for n,v in balances.items() if v >  0.5])
    pagos = []
    i=j=0
    while i<len(deudores) and j<len(acreedores):
        nd,da = deudores[i]; na,ca = acreedores[j]
        m = min(da,ca); pagos.append((nd,na,round(m)))
        da-=m; ca-=m; deudores[i]=(nd,da); acreedores[j]=(na,ca)
        if da<=0.5: i+=1
        if ca<=0.5: j+=1
    return pagos
```

---

## 5. Flujos / pantallas (MVP)
**Repartir cuenta:**
1. Crear grupo → agregar comensales (nombres) → compartir link.
2. Subir foto de la factura → `ImagenUpload` → preset A → revisar ítems detectados.
3. Elegir reparto: **Equitativo** (un toque) o **Por producto**:
   - Asignar cada ítem tocando comensales, **o** por **chat de voz** (`ChatCaptura` + preset B):
     *"el pastel entre todos, la pizza Juan, las michveladas Ana y yo"*.
4. Indicar quién pagó → ver **balances** y la lista mínima de pagos.
5. Registrar pagos (settlements) para ir saldando.

**Gastos personales:**
1. `ChatCaptura`/`ImagenUpload` (preset C): "me gasté 100.000 en el bar".
2. Lista + resúmenes por categoría/mes.

---

## 6. Endpoints backend (FastAPI)
```
# Auth (solo dueño)
POST /api/auth/login            # Google OAuth o magic link

# Grupos / comensales
POST /api/grupos               GET /api/grupos
GET  /api/grupos/{id}          POST /api/grupos/{id}/comensales
GET  /api/g/{share_token}      # acceso invitado por link

# Repartir cuenta
POST /api/grupos/{id}/cuenta/extraer    # foto -> preset A -> items
POST /api/grupos/{id}/cuenta            # crear expense + items
POST /api/cuenta/{id}/asignar/chat      # preset B (voz/texto) -> asignaciones
POST /api/cuenta/{id}/asignar           # asignación manual desde UI
GET  /api/grupos/{id}/balances          # neto + lista mínima de pagos
POST /api/grupos/{id}/pagos             # registrar settlement

# Gastos personales
POST /api/gastos/extraer   POST /api/gastos/chat
GET  /api/gastos           GET /api/gastos/resumen
```

---

## 7. Stack y despliegue
- **Frontend:** React + Vite + Tailwind (copiar tema + componentes `ImagenUpload`, `ChatCaptura`).
- **Backend:** FastAPI + `loggro_intake` (copiado, renombrar a `intake`).
- **DB:** Postgres en **Neon** o **Supabase** (free tier). Usar **connection string con pooler**
  (PgBouncer) por el entorno serverless de Vercel. ORM: SQLAlchemy (o `asyncpg` directo).
- **Auth:** Supabase Auth o Google OAuth (solo el dueño necesita cuenta).
- **Deploy:** Vercel (frontend `dist` + `api/index.py` ASGI), igual que Loggro. FS de solo
  lectura → nada de archivos; todo a Postgres. `GEMINI_API_KEY` + `DATABASE_URL` en env vars.
- **Cache opcional:** Redis (Upstash) para catálogos/sesiones, no imprescindible para el MVP.

---

## 8. Reúso concreto desde el proyecto Loggro
**Copiar tal cual:** `loggro_intake/{gemini,extractor,chat}.py`,
`frontend/src/components/{ImagenUpload,ChatCaptura}.tsx`, `tailwind.config.js`,
patrón de `api/index.py` + `vercel.json`.
**Escribir nuevo:** los 3 presets (esquemas + prompts), el modelo Postgres + migraciones,
los endpoints, la lógica de reparto/liquidación, y las pantallas.

---

## 9. MVP vs. después
**MVP (ambos flujos):** crear grupo + comensales (link), factura por foto, reparto equitativo
y por producto (UI + chat de voz), balances + pagos; gastos personales por voz/texto + resumen.
**Después:** login de invitados (que reclamen su nombre), notificaciones/recordatorios de pago,
multi-moneda, exportar/compartir resumen, fotos de soporte por gasto, presupuestos y reportes
de finanzas personales, categorías inteligentes.

---

## 10. Decisiones abiertas (para discutir en Claude web)
- Auth del dueño: Google OAuth vs magic link (Supabase simplifica ambos).
- ¿Los invitados podrán "reclamar" su nombre creando cuenta más adelante? (afecta `participants.user_id`).
- Manejo de propina/impuestos: prorrateo proporcional (propuesto) vs split aparte.
- ¿Una sola foto = una cuenta, o permitir varias facturas por evento?
- Moneda única (COP) en MVP vs multi-moneda desde ya.
