# API de Carta (catálogo) — Loggro

API para que **Apptender** —o cualquier otra aplicación— cree productos, cambie
**nombre** y **precio**, y **active/desactive** productos en Loggro (el POS), usando
siempre **su propio código único** como identificador.

La app externa **nunca necesita conocer el `_id` de Loggro**. El vínculo
`código externo → producto de Loggro` lo guarda esta API.

```
  Apptender                     API de carta                    Loggro (POS)
  ─────────                     ────────────                    ────────────
  codigo = "APT-001"   ──────►  busca el vínculo      ──────►   POST /products
  precio = 6000                 (o lo crea)                     (crea / edita)
                       ◄──────  GET /cambios          ◄──────   modifiedOn
```

---

## 1. Concepto clave: el código único

Cada producto de la app externa tiene un **código único e inmutable** (`codigo`).
Ese código es el contrato. Mientras no cambie:

- El producto puede **renombrarse**, cambiar de **precio** o **desactivarse** desde
  cualquier app y siempre se sabe a qué producto de Loggro apunta.
- Varias apps pueden convivir: cada una tiene su propio espacio de códigos
  (`app_id`), así que `APT-001` de Apptender y `APT-001` de otra app son distintos.
- Un mismo producto de Loggro **no puede** estar vinculado a dos códigos: la API lo
  rechaza para evitar que dos apps se pisen el mismo producto.

> **Por qué el código no se guarda dentro de Loggro:** se probó enviar `sku`, `code`,
> `barCode`, `reference` y `externalIntegration.apptender` en `POST /products` y Loggro
> los descarta (su esquema solo acepta `externalIntegration.rappi`). Por eso el mapa de
> homologación vive en esta API, sobre el mismo Redis que ya usa la homologación de compras.

---

## 2. Autenticación

Todas las llamadas requieren el header:

```
X-API-Key: <clave de la app>
```

Las claves se configuran en la variable de entorno del servidor:

```
CATALOGO_API_KEYS=apptender:CLAVE_LARGA_ALEATORIA,otraapp:OTRA_CLAVE
```

El texto antes de `:` es el `app_id` con el que quedan marcados los vínculos.
Para generar una clave: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

| Respuesta | Significado |
|---|---|
| `401` | Falta el header o la clave no es válida |
| `503` | El servidor no tiene `CATALOGO_API_KEYS` configurada |

En desarrollo local se puede omitir la autenticación con `CATALOGO_DEV_APP=apptender`.

---

## 3. Puesta en marcha (una sola vez): la homologación

En Loggro ya existen ~300 productos y en Apptender ya existe la carta. Antes de
empezar a sincronizar hay que **emparejar** lo que ya existe, para no crear duplicados.

### Paso 1 — Pedir el diagnóstico

`POST /api/catalogo/homologar` — **no escribe nada**, solo compara.

```json
{
  "items": [
    { "codigo": "APT-001", "nombre": "Cerveza Águila Light" },
    { "codigo": "APT-002", "nombre": "Coctel de la casa" }
  ],
  "max_candidatos": 3
}
```

Respuesta:

```json
{
  "app": "apptender", "total": 2, "vinculados": 0, "sugeridos": 1, "nuevos": 1,
  "items": [
    { "codigo": "APT-001", "estado": "sugerido", "candidatos": [
        { "product_id": "67c3a2e1...", "product_name": "Aguila Ligtht",
          "precio_loggro": 7500, "activo": true, "parecido": 0.8 } ] },
    { "codigo": "APT-002", "estado": "nuevo", "candidatos": [] }
  ]
}
```

| `estado` | Qué significa | Qué hacer |
|---|---|---|
| `vinculado` | Ya está homologado | Nada |
| `sugerido` | Hay productos con nombre parecido | Que un humano confirme cuál, y llamar `POST /vinculos` |
| `nuevo` | No se parece a nada de Loggro | Al sincronizar se creará en Loggro |

`parecido` va de 0 a 1 (1 = mismo nombre). La comparación **tolera erratas y acentos**,
porque los nombres del POS los escribió alguien a mano:

| Nombre en la app | Mejor candidato en Loggro | `parecido` |
|---|---|---|
| Aguila Light | Aguila Ligtht | 0.96 |
| Media de Ron Caldas 3 años | Media ron Caldas 3 años | 0.94 |
| Costeñita 175 | Costeñita | 0.82 |
| Cerveza Poker | Poker | 0.80 |

Aun así, **siempre debe confirmarlo una persona**: "Media ron Caldas 3 años" y
"Media ron Caldas 5 años" puntúan casi igual y son productos distintos.

### Paso 2 — Confirmar los emparejamientos

`POST /api/catalogo/vinculos`

```json
{
  "app_name": "Apptender",
  "vinculos": [
    { "codigo": "APT-001", "product_id": "67c3a2e1...", "nombre_origen": "Cerveza Águila Light" }
  ]
}
```

Devuelve `ok` por cada línea. Si el producto de Loggro ya está tomado por otro
código, esa línea responde `ok: false` con el motivo (las demás sí se guardan).

### Paso 3 — De ahí en adelante, solo se sincroniza

Los códigos `nuevo` se crean solos en el primer `POST /api/catalogo/productos`.

---

## 4. Endpoints

Base: `https://<tu-dominio>/api/catalogo`
En local: `http://localhost:8090/api/catalogo` (puertos del proyecto en [PUERTOS.md](PUERTOS.md))

| Método | Ruta | Para qué |
|---|---|---|
| `GET` | `/health` | Verificar clave y conexión |
| `GET` | `/loggro/productos?q=&limit=` | Ver el catálogo de Loggro (para emparejar) |
| `GET` | `/loggro/categorias` | Categorías disponibles en Loggro |
| `POST` | `/homologar` | Diagnóstico de emparejamiento (no escribe) |
| `GET` | `/vinculos` | Códigos ya homologados de la app |
| `POST` | `/vinculos` | Confirmar emparejamientos |
| `DELETE` | `/vinculos/{codigo}` | Romper un vínculo (no toca Loggro) |
| `POST` | `/productos` | **Sincronizar** (crear/actualizar) uno o varios |
| `PATCH` | `/productos/{codigo}` | Cambio puntual de uno |
| `DELETE` | `/productos/{codigo}` | Desactivar (o borrar con `?borrar=true`) |
| `GET` | `/cambios?desde=` | Qué cambió **en Loggro** (flujo inverso) |

---

### 4.1 Sincronizar productos — `POST /productos`

El endpoint principal. Se llama cuando en Apptender se **crea** un producto, se
**cambia el precio** o el **nombre**, o se **desactiva**.

```json
{
  "productos": [
    { "codigo": "APT-001", "precio": 8000 },
    { "codigo": "APT-002", "nombre": "Coctel de la casa", "precio": 22000,
      "categoria": "Cocteles", "descripcion": "", "activo": true }
  ],
  "crear_faltantes": true,
  "location_id": null
}
```

| Campo del producto | Obligatorio | Notas |
|---|---|---|
| `codigo` | **sí** | El código único de la app |
| `nombre` | solo al crear | Si se omite en un update, el nombre no se toca |
| `precio` | no | Precio de venta. Se escribe en la sede de Loggro |
| `activo` | no | `false` = no sale en la carta del POS |
| `categoria` | no | Nombre **o** id de una categoría de Loggro |
| `descripcion` | no | |
| `descontar_inventario` | no | Solo al crear. `false` por defecto |

| Campo de la petición | Por defecto | Notas |
|---|---|---|
| `crear_faltantes` | `true` | `false` = si el código no está vinculado, no crea nada (devuelve `omitido`) |
| `location_id` | todas | Sede de Loggro cuyo precio se actualiza |

Respuesta:

```json
{
  "app": "apptender", "total": 2,
  "resumen": { "actualizado": 1, "creado": 1 },
  "resultados": [
    { "codigo": "APT-001", "accion": "actualizado", "product_id": "67c3a2e1...",
      "producto": { "nombre": "Aguila Ligtht", "precio": 8000, "activo": true, "...": "..." } },
    { "codigo": "APT-002", "accion": "creado", "product_id": "6a6900...", "producto": { "...": "..." } }
  ]
}
```

`accion` puede ser: `creado`, `actualizado`, `sin_cambios`, `omitido`, `error`
(cada línea trae `error` con el motivo; **una línea con error no aborta las demás**).

> **Es idempotente.** Mandar dos veces lo mismo devuelve `sin_cambios` la segunda vez
> y **no escribe en Loggro**. Esto es importante: evita mover el `modifiedOn` del
> producto y disparar falsos cambios en el flujo inverso. Se puede reintentar sin miedo.

Límite: 500 productos por llamada.

### 4.2 Cambio puntual — `PATCH /productos/{codigo}`

```json
{ "precio": 9000 }
```

Solo funciona si el código **ya está vinculado** (si no, `404`). Es equivalente a un
`POST /productos` de un solo ítem con `crear_faltantes:false`, pero más directo.

### 4.3 Sacar de la carta — `DELETE /productos/{codigo}`

Por defecto **desactiva** (`isActive = false`), que es lo correcto cuando un producto
"ya no sale": conserva el histórico de ventas y el producto sigue en los reportes.

```
DELETE /api/catalogo/productos/APT-002              -> desactiva
DELETE /api/catalogo/productos/APT-002?borrar=true  -> elimina de Loggro y rompe el vínculo
```

### 4.4 Flujo inverso (Loggro → app) — `GET /cambios`

Loggro **no tiene webhooks**, así que el flujo inverso es por sondeo. La app pregunta
cada cierto tiempo qué cambió en el POS:

```
GET /api/catalogo/cambios?desde=2026-07-28T19:00:00Z
```

```json
{
  "app": "apptender", "desde": "2026-07-28T19:00:00Z",
  "consultado_en": "2026-07-28T19:17:40+00:00", "total": 1,
  "cambios": [
    { "codigo": "APT-002", "product_id": "6a6900...", "estado": "modificado",
      "campos_distintos": ["precio"], "eco_de_esta_api": false,
      "nombre": "Coctel de la casa", "precio": 12345, "activo": false }
  ]
}
```

La app guarda el `consultado_en` de la respuesta y lo manda como `desde` la siguiente vez.

**Anti-eco:** los cambios que hizo esta misma API se descartan comparando contra la
huella del último envío. Sin esto, cada push volvería como si fuera un cambio del POS
y se produciría un bucle. Con `?incluir_eco=true` se ven también esos (para depurar).

`estado` puede ser `modificado` o `eliminado_en_loggro` (alguien borró el producto en
el POS; el vínculo quedó huérfano).

---

## 5. Modelo de sincronización bidireccional

Con solo estos dos endpoints ya hay bidireccionalidad:

- **Apptender → Loggro**: `POST /productos` cuando el usuario guarda un cambio.
- **Loggro → Apptender**: `GET /cambios` cada N minutos; lo que venga con
  `eco_de_esta_api: false` es un cambio hecho en el POS y la app lo aplica en su carta.

**Regla para evitar peleas:** quien cambió de último, gana. El `POST` es idempotente
y `GET /cambios` filtra el eco, así que el sistema converge. Si se necesita que una de
las dos apps mande siempre (por ejemplo, que el precio del POS nunca sobreescriba a
Apptender), esa política se decide del lado de la app al procesar `/cambios`.

Cadencia sugerida para el sondeo: **cada 5–15 minutos**. `GET /cambios` consulta el
catálogo completo de Loggro en cada llamada, así que no conviene hacerlo cada segundo.

---

## 6. Ejemplos

### cURL

```bash
# Verificar
curl -H "X-API-Key: $CLAVE" https://tu-dominio/api/catalogo/health

# Cambiar un precio
curl -X PATCH -H "X-API-Key: $CLAVE" -H "Content-Type: application/json" \
     -d '{"precio": 9000}' \
     https://tu-dominio/api/catalogo/productos/APT-001

# Sincronizar la carta completa
curl -X POST -H "X-API-Key: $CLAVE" -H "Content-Type: application/json" \
     -d '{"productos":[{"codigo":"APT-001","nombre":"Águila Light","precio":8000}]}' \
     https://tu-dominio/api/catalogo/productos
```

### JavaScript (desde Apptender)

```js
const API = "https://tu-dominio/api/catalogo";
const cabeceras = { "Content-Type": "application/json", "X-API-Key": process.env.LOGGRO_API_KEY };

// Se llama al guardar un producto en la carta de Apptender
async function sincronizar(producto) {
  const r = await fetch(`${API}/productos`, {
    method: "POST", headers: cabeceras,
    body: JSON.stringify({ productos: [{
      codigo: producto.id,           // el código único de Apptender
      nombre: producto.nombre,
      precio: producto.precio,
      activo: producto.disponible,
      categoria: producto.categoria,
    }]}),
  });
  const data = await r.json();
  const linea = data.resultados[0];
  if (linea.accion === "error") throw new Error(linea.error);
  return linea;                      // { accion: "actualizado" | "creado" | "sin_cambios", ... }
}
```

---

## 7. Configuración del servidor

| Variable | Obligatoria | Para qué |
|---|---|---|
| `CATALOGO_API_KEYS` | **sí** (en prod) | `app:clave,app2:clave2` |
| `CATALOGO_DEV_APP` | no | Salta la autenticación en local |
| `CATALOGO_CATEGORIA_DEFAULT` | no | Categoría a usar si la app manda una que no existe |
| `REDIS_URL` | **sí** (en Vercel) | Donde se guardan los vínculos. Sin esto no hay persistencia |
| `CORS_ORIGINS` | no | Dominios extra permitidos si se llama desde el navegador |
| `LOGGRO_EMAIL` / `LOGGRO_PASSWORD` | **sí** | Credenciales del POS |
| `LOGGRO_LOCATION_STOCK` | no | Sede por defecto al crear productos |

La API **no crea categorías**. Si la app manda una categoría que no existe en Loggro,
usa la categoría por defecto y devuelve el campo `advertencia` en esa línea.

---

## 8. Comportamiento de Loggro que conviene conocer

Verificado contra la cuenta de pruebas el 2026-07-28:

| Hecho | Consecuencia |
|---|---|
| `POST /products` crea; con `_id` edita; `PUT` no existe | — |
| La edición **no es parcial**: `{_id, price}` responde 500 | La API lee el producto completo, lo modifica y lo reenvía |
| El precio de venta vive en `locationsStock[].price`, no en `price` | La API escribe la sede; solo toca el `price` raíz si el producto ya lo usaba |
| Loggro descarta campos externos (`sku`, `code`, …) | El mapa de códigos es nuestro |
| `DELETE /products/{id}` funciona | Solo con `?borrar=true`; lo normal es desactivar |
| No hay webhooks | El flujo inverso es por sondeo de `modifiedOn` |
| `POST /login` da 500 intermitente | El cliente reintenta solo |
