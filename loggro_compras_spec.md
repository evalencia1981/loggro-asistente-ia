# Especificación — Automatización de compras (Virus Pub → Loggro Restobar)

> Documento de definición para pasar a Claude Code / Cursor.
> Autor: Edward L. Valencia. Estado: borrador funcional v0.1.

## 1. Objetivo

Eliminar la digitación manual de las facturas de compra en Loggro Restobar.
Flujo deseado: **foto de la tirilla → extracción → homologación → registro automático del movimiento "Entrada - Compra" vía API → conciliación**.
Resultado: que **toda** compra quede ingresada y el inventario (y las cuentas por pagar) queden correctos sin trabajo manual.

## 2. Decisión de arquitectura

- **API nativa de Restobar (`https://api.pirpos.com`)**, NO automatización de navegador (RPA).
  - Loggro adquirió PirPos en 2022; Restobar corre sobre `api.pirpos.com`.
  - El endpoint de creación de movimiento (`guardarmovimientoinventario`) es el gemelo de escritura del `GET /inventory`. Equivale exactamente a "Guardar cambios" del modal *Movimiento Inventario*.
- **No se requiere el módulo Enterprise** (`api.loggro.com/apik/loggro-enterprise`). El módulo de inventario ya está en la API de Restobar, bajo el mismo login.
- RPA con Playwright queda como **plan B** solo si el acceso a API no estuviera habilitado en la cuenta.

### Pendiente comercial
- Confirmar con soporte Loggro si "Uso de API" está activo en el plan actual y su costo. Canales: WhatsApp soporte **310 242 9665** (opción Soporte Técnico), chat en Restobar, o tel. 604 604 3120.

## 3. Endpoints (base `https://api.pirpos.com`, auth `Authorization: Bearer {tokenCurrent}`)

| Uso | Método | Ruta | Notas |
|---|---|---|---|
| Login | POST | `/login` | ✅ **CONFIRMADO.** Body: `{ email, password }`. Devuelve `tokenCurrent` (JWT). El servidor devuelve **500 intermitente**: reintentar ante 5xx. Enviar credenciales `null` también produce 500. |
| Tipos de inventario | GET | `/inventories/types/all` | ✅ **CONFIRMADO** (plural). Array `{ id, name, isSubtracted }`. `"Entrada - Compra"` → **`id = 1`**. |
| Productos | GET | `/products` | ✅ **CONFIRMADO.** `_id` de cada producto = `ingredient` del detalle. Soporta `?name=`, `?pagination=true&limit=&page=`. |
| Proveedores (consultar) | GET | `/providers` | ✅ **CONFIRMADO.** Array de `{ _id, name, tradename, document, ... }`. Buscar por NIT en `document`. |
| Proveedores (crear/editar) | POST | `/providers` | ✅ **CONFIRMADO.** Body: `{ name, tradename, document, email, phone, address, web, contact, note }`. Devuelve el objeto con `_id`. |
| Crear/editar movimiento | POST | `/inventories` | ✅ **CONFIRMADO** (escritura probada: status 200, devuelve el objeto con `_id`). Con `_id` en el body = edición. Body = objeto `Inventory` (sección 4.3). |
| Eliminar movimiento | DELETE | `/inventories/{_id}` | ✅ **CONFIRMADO.** Devuelve `{"message":"Eliminado!"}`. Revierte stock y `avgCost`. |
| Consultar movimientos | GET | `/inventories` | ✅ **CONFIRMADO** (plural). Filtros: `provider`, `inventoryTypeId`, `inventoryNumber`, `purchaseStatus`, `pagination`, `limit`, `page`. Para conciliar. |
| Pago de factura de inventario | POST | `/inventories/payments` | ⏳ **Ruta por confirmar** (plural asumido, `guardarpagoinventario`). Para abonar/pagar compras pendientes. |

> NOTA: la API real usa rutas en **plural** (`/inventories`), no `/inventory`. El portal developer.loggro.com limita con 429 cuando se consulta muy seguido.

## 4. Modelo de datos

### 4.1 Extracción (salida del modelo de visión)
```json
{
  "proveedor": { "nombre_tirilla": "string", "nit": "string" },
  "documento": { "numero": "string", "tipo": "PRECUENTA_COPIA|FACTURA", "forma_pago": "CONTADO|CREDITO", "pagado": false },
  "items": [
    { "cod_proveedor": "string", "descripcion": "string", "um": "string",
      "cantidad": 0, "total": 0, "base": 0, "iva_pct": 0, "iva": 0, "ic_licores": 0 }
  ],
  "totales": { "base": 0, "iva": 0, "ic_licores": 0, "total_pagar": 0 },
  "cuadra": true
}
```
Validación dura: `sum(items.total) == totales.total_pagar`. Si no cuadra, no se procesa (queda en bandeja de revisión).

### 4.2 Homologación
Mapa persistente `descripcion/cod_proveedor (de la tirilla) → product._id (Loggro)`.
- Se construye una vez por producto; crece y se reutiliza.
- Si un ítem no está homologado, el bot **se detiene en esa línea** y la marca para mapeo manual (no adivina).
- Archivo sugerido: `homologacion.json` → `{ "POKER 330ML": "507f1f77bcf86cd799439013", ... }`.

### 4.3 Payload del movimiento (objeto `Inventory`) — mapeo modal → API
> **Esquema validado** contra movimientos reales leídos de `GET /inventories` (type=1).
> Diferencias vs. la versión inicial del spec: existe `total` a nivel raíz; cada línea
> lleva `locationStock` (obligatorio) y `note`; `invoice` solo trae
> `invoiceNumber/isPaid/total` (los campos `totalPaid`/`subtractCashRegister` NO aparecen
> en las compras guardadas → pertenecen al flujo de pago `POST /inventories/payments`).

| Campo modal | Campo API | Origen |
|---|---|---|
| Fecha | `date` (ISO date-time) | extracción |
| Tipo (Entrada - Compra) | `type` (number, = 1) | resuelto desde `/inventories/types/all` |
| Total factura | `total` (raíz) y `invoice.total` | `totales.total_pagar` |
| Factura No. | `invoice.invoiceNumber` | extracción |
| (pagado/pendiente) | `invoice.isPaid` | extracción |
| Proveedor | `provider` (`_id` o `null`) | homologación de proveedor |
| Nota | `note` | libre |
| (línea) producto | `ingredients[].ingredient` (`_id`) | homologación |
| (línea) cantidad | `ingredients[].quantity` | extracción |
| (línea) costo unitario | `ingredients[].price` | `total / cantidad` (ver base de costo) |
| (línea) bodega/ubicación | `ingredients[].locationStock` (`_id`) | config (Virus Pub: "General" `67c398d9be2bbaa69edebdf3`) |
| (línea) nota | `ingredients[].note` | libre (`""`) |

Campos generados por el servidor (no enviar): `_id`, `typeName`, `total` puede recalcularse, `ingredients[]._id`, `quantityVoided`, `voidStatus`, etc.

Ejemplo (tirilla "Donde el Calvo", costo con impuestos incluidos):
```json
{
  "date": "2026-06-01T00:00:00.000Z",
  "type": 1,
  "provider": "6a1e7c149db76c19017d5fbe",
  "note": "Compra Donde el Calvo (precuenta)",
  "total": 363663,
  "invoice": { "invoiceNumber": "DEC0001", "isPaid": false, "total": 363663 },
  "ingredients": [
    { "ingredient": "67c3a250ad3161833cb217c3", "quantity": 60, "price": 2290,  "locationStock": "67c398d9be2bbaa69edebdf3", "note": "" },
    { "ingredient": "67c3a2150a1f43ca347c55a9", "quantity": 60, "price": 2376,  "locationStock": "67c398d9be2bbaa69edebdf3", "note": "" },
    { "ingredient": "<id_bacardi_pendiente>",   "quantity": 1,  "price": 52788, "locationStock": "67c398d9be2bbaa69edebdf3", "note": "" },
    { "ingredient": "67c3ca1a23f00639bf4191a1", "quantity": 1,  "price": 22977, "locationStock": "67c398d9be2bbaa69edebdf3", "note": "" },
    { "ingredient": "67c398dabe2bbaa69edebe27", "quantity": 2,  "price": 3969,  "locationStock": "67c398d9be2bbaa69edebdf3", "note": "" }
  ]
}
```

### Base de costo (decisión de negocio)
- `price` por defecto = `total_linea / cantidad` (incluye IVA + IC). Cuadra con lo realmente pagado.
- Alternativa: `price = base / cantidad` (sin IVA). El IC a licores normalmente sí va al costo.
- Definir una sola política y dejarla parametrizada (`COST_BASIS = "con_impuestos" | "sin_iva"`).

## 5. Pipeline
1. **Captura**: foto de la tirilla (móvil) → almacenamiento.
2. **Extracción**: modelo de visión → JSON sección 4.1.
3. **Homologación**: resolver `provider` e `ingredient._id`; ítems sin mapa → revisión.
4. **Construcción**: armar objeto `Inventory` (sección 4.3) con validación de cuadre.
5. **Carga**: `POST /inventory`.
6. **Conciliación**: `GET /inventory?inventoryNumber=...` → confirmar que existe y que `invoice.total` coincide.
7. **Pago** (opcional): `POST /inventory/payments` si la compra se paga; si no, queda `isPaid:false`.

### v1 = humano en el bucle
El bot arma y muestra el payload + el cuadre; una persona aprueba antes de `POST`. Cuando haya confianza, v2 hace `POST` automático solo si cuadra.

## 6. Controles (responde "¿cómo aseguro que todo entre y el inventario esté bien?")
- **Estados por factura**: `capturada → extraída → homologada → cargada → conciliada`.
- **Cuadre obligatorio**: `sum(líneas) == total factura`; si no, no se carga.
- **Anti-duplicado**: clave única `(provider + invoiceNumber + fecha)`; verificar con `GET /inventory?inventoryNumber=` antes de cargar.
- **Pendientes por pagar**: `GET /inventory?purchaseStatus=false` → listado de lo que falta pagar.
- **Compras faltantes**: cualquier producto con stock negativo = compra no ingresada → alerta.

## 7. Configuración requerida
- `LOGGRO_BASE_URL` (default `https://api.pirpos.com`)
- `LOGGRO_EMAIL`, `LOGGRO_PASSWORD` (en `.env`, nunca en el repo)
- `LOGGRO_LOCATION_STOCK` (default `67c398d9be2bbaa69edebdf3` = bodega "General" de Virus Pub)
- `type` de "Entrada - Compra" (resuelto en runtime; **confirmado = 1**)
- `homologacion.json` (productos) y mapa de proveedores por NIT
- `COST_BASIS`

## 8. Seguridad
- Credenciales en variables de entorno / `.env` fuera de control de versiones.
- Token JWT en memoria; renovar al expirar (401 → re-login).
- v1 con aprobación humana antes de escribir.

## 9. Pendientes por confirmar
1. ✅ Creación de movimiento: `POST /inventories` **confirmada** (escritura probada,
   status 200). Eliminación: `DELETE /inventories/{_id}`. **Nota de stock:** el stock real
   vive en `product.locationsStock[].stock` (por bodega), NO en `product.stock` (raíz, =0).
   El campo `avgCost` por ubicación se recalcula al crear/eliminar movimientos.
2. ✅ Ruta de proveedores: `GET`/`POST /providers` **confirmadas**. ⏳ Ruta de pagos
   `POST /inventories/payments` aún sin confirmar.
3. ✅ Campos del body de `/login`: `{ email, password }`. (Ojo: 500 intermitente del
   servidor → reintentar; credenciales `null` también dan 500, no 400.)
4. ✅ `id` real de "Entrada - Compra" = **1** (`GET /inventories/types/all`).
5. ✅ Acceso a API habilitado: la cuenta lee y escribe (se creó un proveedor de prueba).

> **Validado el 2026-06-02** con la cuenta `vpubrock@gmail.com` (negocio "Virus pub"):
> 291 productos, 9 proveedores, 685 movimientos. Proveedor de prueba "DONDE EL CALVO"
> creado con `_id = 6a1e7c149db76c19017d5fbe`.

## 10. Plan de construcción (checklist)
- [x] Confirmar acceso a API y los pendientes de la sección 9 (login, types, products, providers, get-movimientos).
- [x] `loggro_client.py`: login (con reintentos), types, products, providers (get+create), get-movimientos. ⏳ Falta probar `create_movement`/`payment` (escritura).
- [x] Capa de homologación (`homologacion.json` + resolver) — validada con la tirilla "Donde el Calvo".
- [ ] Extractor de tirilla (visión) → JSON 4.1 + validación de cuadre.
- [ ] Orquestador: extracción → homologación → payload → (aprobación) → POST → conciliación.
- [ ] Job de control: pendientes por pagar y stocks negativos.
- [ ] Pruebas con las 5 facturas piloto.
