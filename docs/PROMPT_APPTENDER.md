# Prompt para Apptender — Integración de la carta con Loggro (POS)

> **Cómo usar este documento:** ábrelo en el repositorio de Apptender y pásaselo a Claude
> Code (o al desarrollador) como especificación. Es autocontenido: no hace falta conocer
> el proyecto de Loggro. Los pasos están pensados para hacerse **en orden**; cada uno se
> puede probar antes de seguir al siguiente.

---

## 0. Contexto y objetivo

Apptender tiene una **carta** con productos que cambian de precio, cambian de nombre, se
crean y se desactivan cuando ya no salen. Loggro (el POS del negocio, en
`https://api.pirpos.com`) tiene su propio catálogo con esos mismos productos.

**Objetivo:** que un cambio en la carta de Apptender se refleje en Loggro, y que un cambio
hecho en el POS se pueda traer de vuelta a Apptender.

**Decisión de arquitectura ya tomada:** Apptender habla **directo** con la API de Loggro.
No hay capa intermedia. Apptender guarda el `_id` del producto de Loggro en un campo de su
propia tabla de productos — ese campo es todo el vínculo que existe.

```
  Apptender (Node + Vue)                         Loggro (api.pirpos.com)
  ──────────────────────                         ───────────────────────
  producto.loggro_product_id  ──────────────►    POST /products (crear/editar)
  producto.loggro_modified_on ◄──────────────    GET /products  (detectar cambios)
```

---

## 1. Hechos verificados de la API de Loggro

Todo lo de esta sección se **probó contra la cuenta real** el 2026-07-28. No asumas nada
que no esté aquí; la API de Loggro no tiene documentación pública ni OpenAPI.

### Autenticación

```
POST https://api.pirpos.com/login
Body: { "email": "...", "password": "..." }
Respuesta: { "tokenCurrent": "<JWT>", ... }
```

- El token va en `Authorization: Bearer <tokenCurrent>`.
- **El login devuelve 500 de forma intermitente.** Hay que reintentar (2–3 veces). Un 400
  sí es credenciales malas y no se debe reintentar.
- Un 401 en cualquier llamada = token vencido → volver a hacer login y reintentar una vez.
- ⚠️ **El token da acceso total a la cuenta**: ventas, cajas, inventario, gastos. No hay
  permisos ni scopes. Trata esas credenciales como las de producción que son: variables de
  entorno, nunca en el repositorio, nunca en logs.

### Lectura

| Ruta | Devuelve |
|---|---|
| `GET /products` | Todos los productos (~305). Acepta `?name=` y `?pagination=false` |
| `GET /products/{id}` | Un producto completo |
| `GET /categories` | Categorías de la carta (~18) |
| `GET /taxes` | Impuestos configurados |

`GET /products` puede devolver un array o un objeto `{data: [...]}` — soporta los dos casos.

### Escritura

| Operación | Cómo |
|---|---|
| Crear | `POST /products` con el payload → devuelve el objeto creado **con su `_id`** |
| Editar | `POST /products` con `_id` dentro del body |
| Eliminar | `DELETE /products/{id}` |
| ~~`PUT /products/{id}`~~ | **No existe** (404) |

### Las cuatro trampas

Estas son las que cuestan tiempo y dinero. Léelas dos veces.

**1. La edición NO es parcial.**
Mandar `{"_id": "...", "price": 9000}` responde **500** con
`"Se produjo un error al guardar el producto. Verifique que el producto se encuentre en
éste negocio."`. Hay que hacer **read-modify-write**: `GET /products/{id}`, modificar los
campos en el objeto completo, y devolver ese objeto entero por `POST /products`. El objeto
tal como lo entrega el GET se acepta con las referencias anidadas (`category`,
`locationStock` como objetos) o aplanadas a ids — las dos formas funcionan.

**2. El precio de venta NO está en `price`.**
Está en `locationsStock[].price`, que es el precio por sede. En los productos creados desde
el POS el `price` de la raíz está en **0**:

```json
{ "name": "1/4 aguardiente rojo", "price": 0,
  "locationsStock": [ { "locationStock": {...}, "price": 28000 } ] }
```

Si escribes solo el `price` de la raíz, **la API responde 200, todo se ve bien, y el POS
sigue vendiendo al precio viejo.** Es un error que no falla: solo cuesta plata.

Regla: escribe siempre `locationsStock[].price`. Toca el `price` de la raíz **solo si ya
venía distinto de 0** (o si el producto no tiene sedes), para no ensuciar el dato.

Para leer el precio: el de la sede `isMain`, si no el de la primera sede, y como último
recurso el de la raíz.

**3. Loggro descarta cualquier código externo.**
Se probó mandar `sku`, `code`, `barCode`, `reference` y `externalIntegration.apptender`:
Loggro los ignora todos (su esquema solo acepta `externalIntegration.rappi`). **No puedes
guardar el id de Apptender dentro del producto de Loggro.** Por eso el vínculo va al revés:
Apptender guarda el id de Loggro.

**4. No hay webhooks.**
Loggro no avisa cuando algo cambia. El flujo inverso se hace por sondeo comparando el campo
`modifiedOn` de cada producto.

### Campos del producto que nos importan

```json
{
  "_id": "688d728571dce77c64eb238a",
  "name": "1/4 aguardiente rojo",
  "description": "",
  "price": 0,
  "isActive": true,
  "category": { "_id": "67c3a1a00a1f43ca347b32c4", "name": "Licores" },
  "locationsStock": [ { "locationStock": { "_id": "67c398d9be2bbaa69edebdf3" }, "price": 28000 } ],
  "modifiedOn": "2025-08-13T23:21:51.132Z"
}
```

- `isActive: false` = el producto no sale en la carta del POS. **Es lo que hay que usar
  cuando un producto "ya no sale"**, no el DELETE: conserva el histórico de ventas.
- `modifiedOn` lo actualiza Loggro en cada escritura.

### Payload mínimo verificado para crear

```json
{
  "name": "Limonada de coco",
  "description": "",
  "price": 15000,
  "type": "Normal",
  "isActive": true,
  "isIngredient": false,
  "isSubproduct": false,
  "discountInventory": false,
  "inventoryType": "PerUnit",
  "ingredients": [], "extra": [], "subProducts": [],
  "category": "<id de categoría>",
  "locationsStock": [
    { "locationStock": "<id de sede>", "price": 15000, "stock": 0,
      "stockMinimum": 0, "pricePurchase": 0, "isMain": true, "taxes": [] }
  ]
}
```

El **id de sede** se obtiene una vez de cualquier producto existente:
`producto.locationsStock[0].locationStock._id`. En la cuenta actual es
`67c398d9be2bbaa69edebdf3` (bodega "General"). Resuélvelo dinámicamente y cachéalo, no lo
dejes escrito a mano.

---

## 2. Cambios en el modelo de datos de Apptender

Agregar a la tabla de productos:

| Campo | Tipo | Para qué |
|---|---|---|
| `loggro_product_id` | string, nullable, **índice único** | El `_id` del producto en Loggro. `null` = no vinculado |
| `loggro_modified_on` | string/date, nullable | El `modifiedOn` que tenía el producto la última vez que sincronizamos. Sirve para detectar cambios hechos en el POS |
| `loggro_synced_at` | date, nullable | Cuándo fue el último envío exitoso (diagnóstico) |

El índice único en `loggro_product_id` es importante: impide que dos productos de Apptender
apunten al mismo producto de Loggro, que es el error más difícil de detectar después.

---

## 3. Paso 1 — Cliente de Loggro (Node)

Un módulo que encapsule login, token y reintentos. Todo lo demás se construye encima.

```js
// services/loggro/client.js
const BASE = process.env.LOGGRO_BASE_URL || "https://api.pirpos.com";

let token = null;

async function login(intentos = 3) {
  for (let i = 1; i <= intentos; i++) {
    const r = await fetch(`${BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: process.env.LOGGRO_EMAIL,
        password: process.env.LOGGRO_PASSWORD,
      }),
    });
    if (r.ok) {
      const d = await r.json();
      token = d.tokenCurrent || d.token;
      if (!token) throw new Error("El login no devolvió token");
      return token;
    }
    // 500 de PirPos = fallo transitorio, se reintenta. 4xx = credenciales, no.
    if (r.status < 500 || i === intentos) {
      throw new Error(`Login falló (${r.status}): ${(await r.text()).slice(0, 200)}`);
    }
  }
}

async function pedir(metodo, ruta, cuerpo, reintentado = false) {
  if (!token) await login();
  const r = await fetch(`${BASE}${ruta}`, {
    method: metodo,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(cuerpo ? { "Content-Type": "application/json" } : {}),
    },
    ...(cuerpo ? { body: JSON.stringify(cuerpo) } : {}),
  });
  if (r.status === 401 && !reintentado) {   // token vencido -> re-login y un reintento
    token = null;
    return pedir(metodo, ruta, cuerpo, true);
  }
  if (!r.ok) {
    // Importante: mostrar el mensaje real de Loggro, no solo el código.
    throw new Error(`${r.status} en ${ruta}: ${(await r.text()).slice(0, 400)}`);
  }
  return r.json();
}

const desempacar = (d) => (Array.isArray(d) ? d : d?.data ?? d);

export const loggro = {
  listarProductos: () => pedir("GET", "/products?pagination=false").then(desempacar),
  obtenerProducto: (id) => pedir("GET", `/products/${id}`),
  listarCategorias: () => pedir("GET", "/categories").then(desempacar),
  crearProducto: (payload) => pedir("POST", "/products", payload),
  // OJO: payload DEBE ser el producto completo con _id. Ver paso 2.
  editarProducto: (payload) => pedir("POST", "/products", payload),
  eliminarProducto: (id) => pedir("DELETE", `/products/${id}`),
};
```

**Prueba de este paso:** un script que haga login, liste los productos e imprima cuántos
hay y el primero. Si eso funciona, el resto es construcción.

---

## 4. Paso 2 — Capa de productos (traducción y escritura segura)

Aquí es donde se resuelven las trampas 1 y 2. Nada del resto de Apptender debería hablar
con `client.js` directamente: todo pasa por acá.

```js
// services/loggro/productos.js
import { loggro } from "./client.js";

// --- lectura: precio real del producto ---
export function precioDe(p) {
  const sedes = p.locationsStock || [];
  const principal = sedes.find((l) => l.isMain && l.price);
  if (principal) return principal.price;
  const cualquiera = sedes.find((l) => l.price);
  if (cualquiera) return cualquiera.price;
  return p.price || 0;
}

// --- forma canónica que usa Apptender ---
export function aVista(p) {
  return {
    loggroId: p._id,
    nombre: p.name || "",
    precio: precioDe(p),
    activo: !!p.isActive,
    categoria: p.category?.name ?? null,
    categoriaId: p.category?._id ?? p.category ?? null,
    modifiedOn: p.modifiedOn,
  };
}

// --- escritura del precio (trampa 2) ---
function fijarPrecio(obj, precio) {
  const sedes = obj.locationsStock || [];
  // El price de la raíz solo se toca si el producto ya lo usaba, o si no tiene sedes.
  if (!sedes.length || obj.price) obj.price = precio;
  for (const l of sedes) l.price = precio;
}

/**
 * Actualiza un producto existente. Read-modify-write (trampa 1).
 * `cambios` puede traer: { nombre, precio, activo, descripcion, categoriaId }
 * Lo que no venga, no se toca.
 * Devuelve { producto, hubopCambio }.
 */
export async function actualizar(loggroId, cambios) {
  const actual = await loggro.obtenerProducto(loggroId);
  if (!actual?._id) throw new Error(`El producto ${loggroId} ya no existe en Loggro`);

  let cambio = false;
  if (cambios.nombre != null && actual.name !== cambios.nombre) {
    actual.name = cambios.nombre; cambio = true;
  }
  if (cambios.descripcion != null && (actual.description || "") !== cambios.descripcion) {
    actual.description = cambios.descripcion; cambio = true;
  }
  if (cambios.activo != null && !!actual.isActive !== !!cambios.activo) {
    actual.isActive = !!cambios.activo; cambio = true;
  }
  if (cambios.categoriaId) {
    const catActual = actual.category?._id ?? actual.category;
    if (catActual !== cambios.categoriaId) { actual.category = cambios.categoriaId; cambio = true; }
  }
  if (cambios.precio != null && precioDe(actual) !== cambios.precio) {
    fijarPrecio(actual, cambios.precio); cambio = true;
  }

  // Si nada cambió, NO escribir: evita mover modifiedOn y disparar
  // falsos "cambios del POS" en el flujo inverso (paso 6).
  if (!cambio) return { producto: actual, huboCambio: false };

  const guardado = await loggro.editarProducto(actual);
  return { producto: guardado?._id ? guardado : actual, huboCambio: true };
}

export async function crear({ nombre, precio = 0, categoriaId, descripcion = "",
                             activo = true, sedeId }) {
  const creado = await loggro.crearProducto({
    name: nombre, description: descripcion, price: precio,
    type: "Normal", isActive: activo,
    isIngredient: false, isSubproduct: false,
    discountInventory: false, inventoryType: "PerUnit",
    ingredients: [], extra: [], subProducts: [],
    category: categoriaId,
    locationsStock: [{ locationStock: sedeId, price: precio, stock: 0,
                      stockMinimum: 0, pricePurchase: 0, isMain: true, taxes: [] }],
  });
  return creado;   // trae el _id que hay que guardar en Apptender
}

// "Ya no sale" = desactivar, NO borrar (conserva el histórico de ventas).
export const desactivar = (loggroId) => actualizar(loggroId, { activo: false });
```

**Prueba de este paso:** crear un producto de prueba (`"ZZ TEST ..."`), cambiarle el precio,
verificar con `GET /products/{id}` que el precio quedó en `locationsStock[0].price`,
desactivarlo y borrarlo. Ese ciclo completo está verificado y funciona.

---

## 5. Paso 3 — Emparejamiento (matcher)

En Loggro ya existen ~305 productos y en Apptender ya existe la carta. **Antes de
sincronizar hay que emparejar lo que ya existe**, o se duplica todo.

Los nombres del POS los escribió alguien a mano y tienen erratas ("Aguila Ligtht"), así que
comparar por texto exacto no sirve. Este algoritmo combina similitud por palabras con
similitud por caracteres (coeficiente de Dice sobre bigramas), no necesita dependencias, y
está probado contra los 305 productos reales:

```js
// services/loggro/matcher.js
export function normalizar(s) {
  return (s || "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")  // quita acentos (escapes, no literales)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

// Dice sobre bigramas de caracteres: es lo que salva las erratas.
function dice(a, b) {
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return 0;
  const bigramas = (s) => {
    const m = new Map();
    for (let i = 0; i < s.length - 1; i++) {
      const g = s.slice(i, i + 2);
      m.set(g, (m.get(g) || 0) + 1);
    }
    return m;
  };
  const ma = bigramas(a), mb = bigramas(b);
  let comunes = 0, totalA = 0, totalB = 0;
  for (const [g, n] of ma) { totalA += n; if (mb.has(g)) comunes += Math.min(n, mb.get(g)); }
  for (const [, n] of mb) totalB += n;
  return (2 * comunes) / (totalA + totalB);
}

export function parecido(a, b) {
  const na = normalizar(a), nb = normalizar(b);
  if (!na || !nb) return 0;
  if (na === nb) return 1;
  const ta = new Set(na.split(" ")), tb = new Set(nb.split(" "));
  const inter = [...ta].filter((t) => tb.has(t)).length;
  let porPalabras = inter / new Set([...ta, ...tb]).size;
  if (na.includes(nb) || nb.includes(na)) porPalabras = Math.max(porPalabras, 0.8);
  return Math.max(porPalabras, dice(na, nb));
}

/** Devuelve los mejores candidatos de Loggro para un nombre dado. */
export function candidatos(nombre, productosLoggro, max = 3) {
  return productosLoggro
    .map((p) => ({ producto: p, score: parecido(nombre, p.name) }))
    .filter((c) => c.score >= 0.45)
    .sort((a, b) => b.score - a.score)
    .slice(0, max);
}
```

### Umbrales, medidos contra el catálogo real

| Score | Qué significa | Qué hacer |
|---|---|---|
| **≥ 0.85** | Casi siempre correcto | Se puede confirmar en bloque tras una revisión visual |
| **0.55 – 0.85** | Probable, pero hay que mirar | Uno por uno |
| **< 0.55** | Ruido | Tratar como "sin equivalente" y buscar a mano |

Resultados reales del algoritmo:

| Nombre en Apptender | Mejor candidato en Loggro | Score |
|---|---|---|
| Media de Ron Caldas 3 años | Media ron Caldas 3 años | 0.94 |
| Aguila Light | Aguila Ligtht | 0.87 |
| Cerveza Poker | Poker | 0.80 |
| Costeñita 175 | Costeñita | 0.80 |
| Club Colombia Dorada | Club Dorada | 0.69 |
| Producto que no existe | *(nada por encima de 0.22)* | — |

### ⚠️ La regla que evita el error caro

**Si el primer y el segundo candidato están a menos de 0.10 de distancia, hay que forzar
revisión manual**, aunque el primero pase de 0.85.

Caso real: "Media de Ron Caldas 3 años" da 0.936 contra *"Media ron Caldas 3 años"* y
0.851 contra *"Media ron Caldas 5 años"*. Son productos distintos y de precios distintos
($70.000 vs $85.000). Lo mismo pasa con "Coca Cola" y "Coca Cola Zero". El algoritmo no
distingue un número en la mitad del nombre; una persona sí.

En la interfaz, esos casos deben salir marcados y con la diferencia resaltada.

---

## 6. Paso 4 — Pantalla de sincronización (Vue)

Es una pantalla que se usa **una sola vez al conectar**, y después queda como herramienta
de revisión. La clave: no es una pantalla para *asignar* a mano entre 305 opciones, es una
pantalla para **confirmar** lo que el matcher ya propuso.

```
SINCRONIZACIÓN CON LOGGRO                        [ Analizar carta ]

 ✅ Ya vinculados (0)                                          ▸

 ⚠️  Por confirmar (183)                  [ Confirmar los de 85%+ ]
 ┌──────────────────────┬──────────────────────────┬───────┬──────┐
 │ Apptender            │ Loggro (sugerido)        │ Match │      │
 ├──────────────────────┼──────────────────────────┼───────┼──────┤
 │ Aguila Light         │ Aguila Ligtht        ▾   │  87%  │ ✓  ✗ │
 │ $7.500               │ $7.500                   │       │      │
 ├──────────────────────┼──────────────────────────┼───────┼──────┤
 │ Ron Caldas 3 años    │ Media ron Caldas 3 años ▾│  94%  │ ✓  ✗ │
 │ $72.000              │ $70.000  ⚠ precio difiere│ ⚠ hay │      │
 │                      │                          │ otro  │      │
 │                      │                          │ igual │      │
 └──────────────────────┴──────────────────────────┴───────┴──────┘

 🆕 Sin equivalente (17) — se crearán en Loggro                ▸
```

Requisitos de la pantalla:

1. **Tres grupos separados y colapsables**: ya vinculados / por confirmar / sin equivalente.
   El tercero tiene que ser bien visible: esos se van a **crear**, y ahí es donde se duplican
   productos si alguien no mira.
2. **El desplegable de la columna Loggro** trae los otros candidatos y, si ninguno sirve, un
   buscador sobre la lista completa de productos de Loggro (filtro por nombre en el cliente;
   los 305 productos caben de sobra en memoria).
3. **Los dos precios lado a lado.** Es el mejor detector de emparejamientos malos: si el
   nombre calza pero el precio está lejísimos, casi siempre es el producto equivocado.
4. **Marca de "empate"** cuando el segundo candidato está a menos de 0.10 (ver la regla de
   arriba). Esos no entran en la confirmación masiva.
5. **Confirmación masiva por umbral** para los de 85%+.
6. Al confirmar: se guarda `loggro_product_id` y `loggro_modified_on` en el producto de
   Apptender. **Nada se escribe todavía en Loggro.**

### El tercer paso de la pantalla: quién gana

Al terminar de confirmar, mostrar los productos donde el precio de Apptender y el de Loggro
diferían, con la lista a la vista, y preguntar explícitamente:

> *"¿Mandamos los precios de Apptender a Loggro?"*

Porque si después lanzas la sincronización sin más, Apptender pisa los precios del POS en
silencio. Que sea una decisión consciente y no un efecto secundario.

---

## 7. Paso 5 — Envío automático (Apptender → Loggro)

Una vez emparejado, cada vez que en Apptender se guarda un producto:

```js
async function sincronizarConLoggro(producto) {
  if (!producto.loggro_product_id) {
    const creado = await crear({
      nombre: producto.nombre, precio: producto.precio,
      categoriaId: await resolverCategoria(producto.categoria),
      activo: producto.disponible, sedeId: await sedePrincipal(),
    });
    producto.loggro_product_id = creado._id;      // ← guardar SIEMPRE
    producto.loggro_modified_on = creado.modifiedOn;
  } else {
    const { producto: p } = await actualizar(producto.loggro_product_id, {
      nombre: producto.nombre, precio: producto.precio, activo: producto.disponible,
    });
    producto.loggro_modified_on = p.modifiedOn;
  }
  producto.loggro_synced_at = new Date();
  await producto.save();
}
```

Reglas:

- **Nunca hagas el envío dentro de la transacción del guardado.** Loggro puede tardar o
  fallar; el usuario de Apptender no tiene por qué esperar ni perder su cambio. Encolar o
  disparar después de confirmar la transacción.
- **Si el envío falla, no pierdas el pendiente.** Un campo `loggro_pendiente = true` y un
  reintento periódico es suficiente; no hace falta una cola sofisticada.
- **Guardar el `_id` en la creación es crítico.** Si se crea el producto en Loggro y no se
  guarda el id, el próximo guardado crea otro duplicado. Si es posible, guarda el id en la
  misma transacción en que marcas el producto como sincronizado.
- **Desactivar, no borrar**: cuando un producto "ya no sale", `activo: false`. El `DELETE`
  déjalo para casos excepcionales.

---

## 8. Paso 6 — Flujo inverso (Loggro → Apptender)

No hay webhooks: es sondeo. Una tarea cada 5–15 minutos:

```js
async function traerCambiosDeLoggro() {
  const productos = await loggro.listarProductos();
  const porId = new Map(productos.map((p) => [p._id, p]));

  for (const local of await productosVinculados()) {   // los que tienen loggro_product_id
    const remoto = porId.get(local.loggro_product_id);

    if (!remoto) {                       // lo borraron en el POS
      await marcarHuerfano(local);
      continue;
    }
    if (remoto.modifiedOn === local.loggro_modified_on) continue;   // nada cambió

    // Cambió en Loggro después de nuestro último envío.
    const v = aVista(remoto);
    await registrarCambioDelPos(local, v);   // aplicar, o dejar para revisión
    local.loggro_modified_on = remoto.modifiedOn;
    await local.save();
  }
}
```

**Por qué funciona sin más estado:** guardamos el `modifiedOn` en cada envío. Si el
`modifiedOn` que trae Loggro es el mismo que guardamos, el último cambio fue nuestro. Si es
distinto, alguien tocó el producto en el POS.

Esto depende de que el paso 2 **no escriba cuando nada cambió** (por eso la comprobación
`huboCambio`): cada escritura innecesaria mueve el `modifiedOn` y genera un falso positivo.

**Qué hacer con el cambio ajeno** es una decisión de producto. Lo más seguro para empezar:
no aplicarlo automáticamente, sino dejarlo en una bandeja de "cambios hechos en el POS" para
que alguien decida. Si más adelante quieres que se aplique solo, que sea por campo (aceptar
precio pero no nombre, por ejemplo).

---

## 9. Errores que no fallan

Los peligrosos son los que responden 200:

| Error | Síntoma | Cómo evitarlo |
|---|---|---|
| Escribir solo `price` de la raíz | La API responde 200 y el POS sigue vendiendo al precio viejo | Escribir `locationsStock[].price` |
| Crear en Loggro y no guardar el `_id` | Duplicados que se multiplican en cada guardado | Guardar el id apenas se crea |
| Sincronizar antes de emparejar | Se duplica toda la carta | Emparejar primero (paso 3 y 4) |
| Confirmar un emparejamiento por score alto sin mirar | "3 años" queda apuntando a "5 años" | Regla del empate < 0.10 |
| Reescribir aunque nada cambió | `modifiedOn` se mueve y el flujo inverso reporta falsos cambios | Comprobar `huboCambio` |
| Dos productos de Apptender con el mismo `loggro_product_id` | Se pisan entre ellos, imposible de diagnosticar | Índice único en la columna |

---

## 10. Cómo probar

Hazlo en este orden; cada punto depende del anterior:

1. **Login y lectura.** Un script que liste los productos e imprima cuántos hay.
2. **Ciclo de escritura completo** con un producto de prueba llamado `"ZZ TEST ..."`:
   crear → cambiar precio → verificar que quedó en `locationsStock[0].price` →
   cambiar nombre → desactivar → borrar. **Comprobar que no quedó nada.**
3. **Idempotencia**: mandar el mismo cambio dos veces. La segunda debe detectar que no hay
   cambio y no escribir.
4. **Matcher**: correrlo contra la carta real y revisar a mano los primeros 20 resultados.
   Si algo no cuadra, ajustar antes de construir la pantalla.
5. **Pantalla**: emparejar la carta completa con una persona revisando.
6. **Flujo inverso**: cambiar un precio a mano en el POS y comprobar que el sondeo lo detecta.

Para todas las pruebas de escritura, usa productos `"ZZ TEST ..."` y **bórralos al
terminar**. Si tocas un producto real para probar, anota el valor original y restáuralo:
lo que estás modificando es el catálogo con el que factura el negocio.

---

## Anexo — Referencia rápida

```
BASE            https://api.pirpos.com
Auth            Authorization: Bearer <tokenCurrent de POST /login>
Sede (General)  67c398d9be2bbaa69edebdf3   (resolver dinámicamente, no hardcodear)

GET    /products              lista (~305)
GET    /products/{id}         uno completo
GET    /categories            categorías (~18)
POST   /products              crear (sin _id) / editar (con _id, objeto COMPLETO)
DELETE /products/{id}         eliminar

Precio de venta     locationsStock[].price      (NO el price de la raíz)
Producto no sale    isActive: false             (NO el DELETE)
Detección de cambio modifiedOn
```
