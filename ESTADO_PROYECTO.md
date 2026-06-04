# Estado del proyecto — Automatización de compras Loggro/Restobar

> Nota de continuación. Última actualización: **2026-06-02**.
> Cuenta de pruebas: `vpubrock@gmail.com` — negocio **"Virus pub"** (API `https://api.pirpos.com`).

## Dónde vamos (resumen)

La **integración con la API está validada de punta a punta** (lectura y escritura).
Falta la parte de **visión (extractor de tirillas)** y el **orquestador** end-to-end.

## API confirmada (todo probado en vivo)

| Operación | Método | Ruta | Notas |
|---|---|---|---|
| Login | POST | `/login` | Body `{email, password}` → `tokenCurrent`. **500 intermitente** → reintentar. |
| Tipos de inventario | GET | `/inventories/types/all` | "Entrada - Compra" = **id 1**. |
| Productos | GET | `/products` | 291 productos. `_id` = `ingredient` del detalle. |
| Proveedores (leer) | GET | `/providers` | 9 proveedores. Buscar NIT en `document`. |
| Proveedores (crear) | POST | `/providers` | `{name, tradename, document, email, phone, address, web, contact, note}`. |
| Movimientos (leer) | GET | `/inventories` | 685 movimientos. Filtros: `inventoryNumber`, `provider`, etc. |
| Movimiento (crear) | POST | `/inventories` | Devuelve objeto con `_id`. Afecta stock y avgCost. |
| Movimiento (eliminar) | DELETE | `/inventories/{_id}` | `{"message":"Eliminado!"}`. Revierte stock y avgCost. |
| Pago de factura | POST | `/inventories/payments` | ⏳ **Sin confirmar** (ruta asumida). |

> Todas las rutas de inventario son **plural** (`/inventories`), no `/inventory`.

## Hallazgos clave (no olvidar)

1. **Stock real** vive en `product.locationsStock[].stock` (por bodega), **NO** en `product.stock` (raíz, siempre 0).
2. **`avgCost`** por ubicación se recalcula al crear/eliminar movimientos → cuidado con precios de prueba (un $1 contamina el costo promedio).
3. Login da **500 intermitente**; credenciales `null` también dan 500 (no 400). `login()` ya reintenta ante 5xx.
4. Consola Windows: forzar UTF-8 (`set PYTHONIOENCODING=utf-8` + `python -X utf8`, o el `sys.stdout.reconfigure` ya incluido en el cliente).

## IDs importantes (cuenta Virus pub)

- Ubicación/bodega "General" (`locationStock`): `67c398d9be2bbaa69edebdf3`
- Tipo "Entrada - Compra": `type = 1`
- Proveedor de prueba "DONDE EL CALVO" (NIT 1039473492): `6a1e7c149db76c19017d5fbe`
- Productos homologados (ver `homologacion.json`):
  - POKER 330ML → `67c3a250ad3161833cb217c3`
  - AGUILA 330ML → `67c3a2150a1f43ca347c55a9` (Aguila Original)
  - STELLA ARTOIS 6PACK → `67c3ca1a23f00639bf4191a1`
  - HEINEKEN 330ML → `67c398dabe2bbaa69edebe27`

## Archivos del proyecto

- `loggro_client.py` — cliente completo (login c/reintentos, lecturas, create/delete movement, create provider). Rutas reales en plural, carga `.env`, fix UTF-8.
- `loggro_compras_spec.md` — especificación actualizada con todo lo confirmado.
- `homologacion.json` — mapa descripción tirilla → `_id` producto (4 ítems).
- `test_lectura.py` — prueba de solo lectura.
- `.env` — credenciales (NO subir a git; ya está en `.gitignore`).

## Próximos pasos (pendientes para v1)

- [ ] **Resolver/crear "Ron Bacardi"** (`POST /products`) y homologarlo, para completar la factura piloto "Donde el Calvo".
- [ ] **Extractor de tirilla** (modelo de visión): foto → JSON sección 4.1 del spec + validación de cuadre.
- [ ] **Orquestador** end-to-end: extracción → homologación → payload → (aprobación humana) → POST → conciliación.
- [ ] Confirmar **`POST /inventories/payments`** con una compra a crédito real.
- [ ] **Resolver proveedor por NIT** automáticamente (buscar en `/providers`, crear si no existe).
- [ ] Job de control: pendientes por pagar (`purchaseStatus=false`) y stocks negativos.
- [ ] Pruebas con las 5 facturas piloto.

## Cómo retomar

```powershell
cd c:\developments\loggro_Mov
# (las dependencias ya están instaladas: requests, python-dotenv)
$env:PYTHONIOENCODING='utf-8'; python -X utf8 test_lectura.py   # prueba de humo
```
