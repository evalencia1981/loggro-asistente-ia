"""
backend/catalogo_api.py — API de CARTA (catálogo de productos) para apps externas.

Permite que Apptender —o cualquier otra app— cree productos, cambie nombre y precio
y los active/desactive en Loggro, usando SIEMPRE su propio código único como
identificador. La app externa nunca necesita conocer el `_id` de Loggro: el vínculo
`código -> _id` vive en `catalogo_store.py` (Redis/KV).

    Apptender                esta API                     Loggro (api.pirpos.com)
    ---------                --------                     -----------------------
    codigo="APT-001"  --->   busca el vínculo      --->    POST /products (crea/edita)
    precio=6000              o lo crea y lo guarda         DELETE /products/{id}

Autenticación: header `X-API-Key`. Las claves se definen en la variable de entorno
    CATALOGO_API_KEYS="apptender:clave_secreta,otraapp:otra_clave"
El texto antes de ':' es el `app_id` con el que quedan marcados los vínculos, así que
dos apps distintas pueden mapear sus propios códigos al mismo Loggro sin pisarse.
En desarrollo se puede saltar la autenticación con CATALOGO_DEV_APP=apptender.

Hechos de la API de Loggro verificados el 2026-07-28 (cuenta Virus pub) que explican
el diseño de este módulo:
  * NO se puede guardar un código externo dentro del producto de Loggro (descarta
    sku/code/barCode/reference y solo acepta `externalIntegration.rappi`) -> por eso
    el mapa de homologación es nuestro.
  * La edición NO es parcial: hay que leer el producto completo, modificarlo y
    reenviarlo (`POST /products` con `_id`). Ver `_aplicar_cambios`.
  * El precio de venta real vive en `locationsStock[].price` (por sede); el `price`
    de la raíz suele estar en 0 en los productos creados desde el POS. Se escriben
    los dos para que queden coherentes.
  * No hay webhooks: el flujo inverso (Loggro -> app) es por sondeo de `modifiedOn`
    contra GET /api/catalogo/cambios.
"""
from __future__ import annotations

import os
import sys
import time
import datetime as dt
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import loggro_session  # noqa: E402
import catalogo_store as cstore  # noqa: E402

router = APIRouter(prefix="/api/catalogo", tags=["catalogo"])

# Umbral de parecido de nombres para proponer un candidato en /homologar.
UMBRAL_SUGERENCIA = 0.45
PRODUCTS_TTL = 60  # segundos de caché del catálogo completo de Loggro


# --------------------------------------------------------------------------- #
# Autenticación por API key
# --------------------------------------------------------------------------- #
def _keys() -> dict[str, str]:
    """{clave: app_id} a partir de CATALOGO_API_KEYS='app1:clave1,app2:clave2'."""
    crudo = os.getenv("CATALOGO_API_KEYS", "")
    mapa: dict[str, str] = {}
    for par in crudo.split(","):
        par = par.strip()
        if not par or ":" not in par:
            continue
        app_id, clave = par.split(":", 1)
        app_id, clave = app_id.strip(), clave.strip()
        if app_id and clave:
            mapa[clave] = app_id
    return mapa


# Declarado como esquema de seguridad (no como un Header suelto) para que /docs
# muestre el boton "Authorize": se pega la clave una vez y aplica a todas las pruebas.
_esquema_api_key = APIKeyHeader(name="X-API-Key", auto_error=False,
                                description="Clave de la app (ver CATALOGO_API_KEYS).")


def app_actual(x_api_key: Optional[str] = Security(_esquema_api_key)) -> str:
    """Identifica la app que llama. Devuelve su `app_id`."""
    mapa = _keys()
    if not mapa:
        dev = os.getenv("CATALOGO_DEV_APP", "").strip()
        if dev:
            return dev  # modo desarrollo: sin claves configuradas
        raise HTTPException(503, "La API de catálogo no tiene claves configuradas. "
                                 "Define CATALOGO_API_KEYS='app:clave' en el entorno.")
    if not x_api_key:
        raise HTTPException(401, "Falta el header X-API-Key.")
    app_id = mapa.get(x_api_key.strip())
    if not app_id:
        raise HTTPException(401, "X-API-Key inválida.")
    return app_id


# --------------------------------------------------------------------------- #
# Utilidades de texto / comparación de nombres
# --------------------------------------------------------------------------- #
def _sin_acentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _tokens(s: str) -> set[str]:
    limpio = "".join(c if c.isalnum() else " " for c in _sin_acentos(s))
    return {t for t in limpio.split() if t}


def _parecido(a: str, b: str) -> float:
    """0..1. 1 = mismo nombre normalizado.

    Combina dos medidas y se queda con la mejor:
      * por palabras (Jaccard), con bono si un nombre contiene al otro
        ('poker' vs 'cerveza poker 330');
      * por caracteres (SequenceMatcher), que es la que salva las **erratas**
        del POS: 'Aguila Light' vs 'Aguila Ligtht' comparte solo una palabra
        (Jaccard 0.33) pero se parece en un 0.92 letra a letra.
    """
    na, nb = _sin_acentos(a), _sin_acentos(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    por_palabras = len(ta & tb) / len(ta | tb) if (ta and tb) else 0.0
    if na in nb or nb in na:
        por_palabras = max(por_palabras, 0.8)
    por_letras = SequenceMatcher(None, na, nb).ratio()
    return round(max(por_palabras, por_letras), 3)


# --------------------------------------------------------------------------- #
# Acceso a Loggro (con caché corta del catálogo completo)
# --------------------------------------------------------------------------- #
_cache: dict[str, Any] = {"products": None, "products_ts": 0.0,
                          "categories": None, "categories_ts": 0.0}


def _productos_loggro(refresh: bool = False) -> list[dict]:
    if _cache["products"] is None or refresh or (time.time() - _cache["products_ts"]) > PRODUCTS_TTL:
        _cache["products"] = loggro_session.cliente().get_products()
        _cache["products_ts"] = time.time()
    return _cache["products"]


def _categorias_loggro(refresh: bool = False) -> list[dict]:
    if _cache["categories"] is None or refresh or (time.time() - _cache["categories_ts"]) > PRODUCTS_TTL:
        _cache["categories"] = loggro_session.cliente().get_categories()
        _cache["categories_ts"] = time.time()
    return _cache["categories"]


def _invalidar_cache() -> None:
    _cache["products_ts"] = 0.0


def _precio_de(p: dict) -> float:
    """Precio de venta del producto: el de la sede (locationsStock) y si no, el raíz.

    En Loggro el precio real vive por sede; el `price` de la raíz queda en 0 en los
    productos creados desde el POS.
    """
    for loc in p.get("locationsStock") or []:
        if loc.get("isMain") and loc.get("price"):
            return loc["price"]
    for loc in p.get("locationsStock") or []:
        if loc.get("price"):
            return loc["price"]
    return p.get("price") or 0


def _vista(p: dict) -> dict:
    """Producto de Loggro -> forma canónica que ven las apps externas."""
    cat = p.get("category")
    return {
        "product_id": p.get("_id"),
        "nombre": p.get("name") or "",
        "precio": _precio_de(p),
        "activo": bool(p.get("isActive")),
        "categoria": (cat or {}).get("name") if isinstance(cat, dict) else cat,
        "categoria_id": (cat or {}).get("_id") if isinstance(cat, dict) else cat,
        "descripcion": p.get("description") or "",
        "modificado_en": p.get("modifiedOn"),
    }


def _resolver_categoria(nombre_o_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(categoria_id, advertencia). Acepta el _id o el nombre de la categoría.

    No crea categorías: si el nombre no existe, cae en CATALOGO_CATEGORIA_DEFAULT
    (o la primera categoría de la cuenta) y devuelve una advertencia para que la app
    sepa que su categoría no se respetó.
    """
    cats = _categorias_loggro()
    if nombre_o_id:
        objetivo = nombre_o_id.strip()
        for c in cats:
            if c.get("_id") == objetivo:
                return objetivo, None
        n = _sin_acentos(objetivo)
        for c in cats:
            if _sin_acentos(c.get("name") or "") == n:
                return c["_id"], None
    por_defecto = os.getenv("CATALOGO_CATEGORIA_DEFAULT", "").strip()
    if por_defecto:
        for c in cats:
            if c.get("_id") == por_defecto or _sin_acentos(c.get("name") or "") == _sin_acentos(por_defecto):
                aviso = (f"La categoría '{nombre_o_id}' no existe en Loggro; se usó la "
                         f"categoría por defecto.") if nombre_o_id else None
                return c["_id"], aviso
    if not cats:
        return None, "La cuenta de Loggro no tiene categorías; el producto puede ser rechazado."
    primera = cats[0]
    aviso = (f"La categoría '{nombre_o_id}' no existe en Loggro; se usó '{primera.get('name')}'."
             if nombre_o_id else f"Sin categoría indicada; se usó '{primera.get('name')}'.")
    return primera["_id"], aviso


# --------------------------------------------------------------------------- #
# Escritura en Loggro
# --------------------------------------------------------------------------- #
def _fijar_precio(payload: dict, precio: float, location_id: Optional[str]) -> None:
    """Escribe el precio en las sedes (todas, o solo `location_id`).

    El `price` de la raíz solo se toca si el producto ya lo usaba (o si no tiene
    sedes): los productos creados desde el POS lo dejan en 0 y el precio de verdad
    vive en `locationsStock[].price`. Escribir la raíz sin necesidad ensuciaría el
    dato y haría ver como "cambiado" algo que el POS nunca usa.
    """
    sedes = payload.get("locationsStock") or []
    if not sedes or payload.get("price"):
        payload["price"] = precio
    for loc in sedes:
        ref = loc.get("locationStock")
        loc_id = ref.get("_id") if isinstance(ref, dict) else ref
        if location_id and loc_id != location_id:
            continue
        loc["price"] = precio


def _crear_en_loggro(nombre: str, precio: float, categoria_id: Optional[str],
                     descripcion: str, activo: bool, location_id: Optional[str],
                     descontar_inventario: bool) -> dict:
    """POST /products. Payload mínimo verificado contra la cuenta Virus pub."""
    loc = location_id or os.getenv("LOGGRO_LOCATION_STOCK", "67c398d9be2bbaa69edebdf3")
    payload = {
        "name": nombre,
        "description": descripcion or "",
        "price": precio,
        "type": "Normal",
        "isActive": activo,
        "isIngredient": False,
        "isSubproduct": False,
        "discountInventory": bool(descontar_inventario),
        "inventoryType": "PerUnit",
        "ingredients": [], "extra": [], "subProducts": [],
        "locationsStock": [{"locationStock": loc, "price": precio, "stock": 0,
                            "stockMinimum": 0, "pricePurchase": 0, "isMain": True,
                            "taxes": []}],
    }
    if categoria_id:
        payload["category"] = categoria_id
    return loggro_session.cliente().create_product(payload)


def _aplicar_cambios(product_id: str, nombre: Optional[str], precio: Optional[float],
                     activo: Optional[bool], descripcion: Optional[str],
                     categoria_id: Optional[str], location_id: Optional[str]) -> tuple[dict, bool]:
    """Read-modify-write sobre un producto existente. -> (producto_actualizado, hubo_cambio).

    Loggro rechaza los updates parciales, así que se lee el producto completo, se
    tocan solo los campos pedidos y se reenvía entero. Si nada cambia no se escribe
    (evita mover `modifiedOn` y disparar falsos cambios en el flujo inverso).
    """
    cli = loggro_session.cliente()
    actual = cli.get_product(product_id)
    if not actual or not actual.get("_id"):
        raise HTTPException(404, f"El producto {product_id} ya no existe en Loggro.")

    cambio = False
    if nombre is not None and (actual.get("name") or "") != nombre:
        actual["name"] = nombre
        cambio = True
    if descripcion is not None and (actual.get("description") or "") != descripcion:
        actual["description"] = descripcion
        cambio = True
    if activo is not None and bool(actual.get("isActive")) != bool(activo):
        actual["isActive"] = bool(activo)
        cambio = True
    if categoria_id:
        cat = actual.get("category")
        cat_actual = cat.get("_id") if isinstance(cat, dict) else cat
        if cat_actual != categoria_id:
            actual["category"] = categoria_id
            cambio = True
    if precio is not None and _precio_de(actual) != precio:
        _fijar_precio(actual, precio, location_id)
        cambio = True

    if not cambio:
        return actual, False
    actualizado = cli.update_product(actual)
    _invalidar_cache()
    return (actualizado if isinstance(actualizado, dict) and actualizado.get("_id") else actual), True


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class ProductoIn(BaseModel):
    codigo: str = Field(..., description="Código único e inmutable del producto en la app origen.")
    nombre: Optional[str] = None
    precio: Optional[float] = None
    activo: Optional[bool] = None
    categoria: Optional[str] = None       # nombre o _id de la categoría en Loggro
    descripcion: Optional[str] = None
    descontar_inventario: bool = False    # solo al crear


class UpsertRequest(BaseModel):
    productos: list[ProductoIn]
    crear_faltantes: bool = True          # si el código no está vinculado, crearlo en Loggro
    location_id: Optional[str] = None     # sede cuyo precio se actualiza (por defecto, todas)


class CambioIn(BaseModel):
    """Cambio puntual sobre un producto ya vinculado (PATCH)."""
    nombre: Optional[str] = None
    precio: Optional[float] = None
    activo: Optional[bool] = None
    categoria: Optional[str] = None
    descripcion: Optional[str] = None
    location_id: Optional[str] = None


class ItemHomologar(BaseModel):
    codigo: str
    nombre: str
    precio: Optional[float] = None


class HomologarRequest(BaseModel):
    items: list[ItemHomologar]
    max_candidatos: int = 3


class VinculoIn(BaseModel):
    codigo: str
    product_id: str
    nombre_origen: Optional[str] = None


class VincularRequest(BaseModel):
    vinculos: list[VinculoIn]
    app_name: Optional[str] = None


# --------------------------------------------------------------------------- #
# Endpoints — lectura / homologación
# --------------------------------------------------------------------------- #
@router.get("/health")
def health(app_id: str = Depends(app_actual)):
    """Comprueba clave y conexión. Útil como primer llamado desde la app externa."""
    return {"ok": True, "app": app_id, "vinculos": len(cstore.app_items(app_id))}


@router.get("/loggro/productos")
def loggro_productos(q: Optional[str] = None, limit: int = 100,
                     refresh: bool = Query(False), app_id: str = Depends(app_actual)):
    """Catálogo actual de Loggro (para emparejar a mano desde una pantalla)."""
    try:
        prods = _productos_loggro(refresh)
    except Exception as e:
        raise HTTPException(502, f"Error consultando productos en Loggro: {e}")
    ocupados = cstore.product_ids_ocupados()
    salida = []
    needle = _sin_acentos(q) if q else None
    for p in prods:
        if needle and needle not in _sin_acentos(p.get("name") or ""):
            continue
        v = _vista(p)
        v["vinculado_a"] = ocupados.get(p.get("_id"))
        salida.append(v)
        if len(salida) >= limit:
            break
    return salida


@router.get("/loggro/categorias")
def loggro_categorias(refresh: bool = Query(False), app_id: str = Depends(app_actual)):
    try:
        cats = _categorias_loggro(refresh)
    except Exception as e:
        raise HTTPException(502, f"Error consultando categorías en Loggro: {e}")
    return [{"id": c.get("_id"), "nombre": c.get("name"), "activa": c.get("isActive")}
            for c in cats]


@router.post("/homologar")
def homologar(req: HomologarRequest, app_id: str = Depends(app_actual)):
    """Cruza la carta de la app con el catálogo de Loggro. **No escribe nada.**

    Para cada ítem devuelve su estado:
      - `vinculado`: el código ya apunta a un producto de Loggro.
      - `sugerido`:  hay candidatos con nombre parecido; hay que confirmar con
                     POST /vinculos.
      - `nuevo`:     no se parece a nada; al hacer upsert se creará en Loggro.
    """
    try:
        prods = _productos_loggro()
    except Exception as e:
        raise HTTPException(502, f"Error consultando productos en Loggro: {e}")

    data = cstore.cargar()
    ocupados = cstore.product_ids_ocupados(data)
    resultado, n_vinc, n_sug, n_nuevo = [], 0, 0, 0

    for it in req.items:
        v = cstore.vinculo(app_id, it.codigo, data)
        if v:
            n_vinc += 1
            resultado.append({"codigo": it.codigo, "nombre": it.nombre, "estado": "vinculado",
                              "product_id": v["product_id"], "product_name": v.get("product_name"),
                              "candidatos": []})
            continue
        puntuados = []
        for p in prods:
            pid = p.get("_id")
            if pid in ocupados:            # ya lo tomó otro código
                continue
            s = _parecido(it.nombre, p.get("name") or "")
            if s >= UMBRAL_SUGERENCIA:
                puntuados.append({"product_id": pid, "product_name": p.get("name"),
                                  "precio_loggro": _precio_de(p),
                                  "activo": bool(p.get("isActive")), "parecido": s})
        puntuados.sort(key=lambda x: x["parecido"], reverse=True)
        candidatos = puntuados[:max(1, req.max_candidatos)]
        estado = "sugerido" if candidatos else "nuevo"
        n_sug, n_nuevo = (n_sug + 1, n_nuevo) if candidatos else (n_sug, n_nuevo + 1)
        resultado.append({"codigo": it.codigo, "nombre": it.nombre, "estado": estado,
                          "product_id": None, "product_name": None, "candidatos": candidatos})

    return {"app": app_id, "total": len(req.items), "vinculados": n_vinc,
            "sugeridos": n_sug, "nuevos": n_nuevo, "items": resultado}


@router.get("/vinculos")
def listar_vinculos(app_id: str = Depends(app_actual)):
    """Todos los códigos ya homologados de esta app."""
    items = cstore.app_items(app_id)
    return {"app": app_id, "total": len(items),
            "vinculos": [{"codigo": e.get("codigo", cod), **{k: v for k, v in e.items() if k != "codigo"}}
                         for cod, e in items.items()]}


@router.post("/vinculos")
def crear_vinculos(req: VincularRequest, app_id: str = Depends(app_actual)):
    """Homologa uno o varios códigos contra productos que YA existen en Loggro."""
    if not req.vinculos:
        raise HTTPException(400, "No se enviaron vínculos.")
    data = cstore.cargar()
    ocupados = cstore.product_ids_ocupados(data)
    salida = []
    for v in req.vinculos:
        dueno = ocupados.get(v.product_id)
        if dueno and dueno != f"{app_id}/{cstore.normalizar_codigo(v.codigo)}":
            salida.append({"codigo": v.codigo, "ok": False,
                           "error": f"Ese producto de Loggro ya está vinculado a {dueno}."})
            continue
        try:
            p = loggro_session.cliente().get_product(v.product_id)
        except Exception as e:
            salida.append({"codigo": v.codigo, "ok": False,
                           "error": f"No se pudo leer el producto en Loggro: {e}"})
            continue
        if not p or not p.get("_id"):
            salida.append({"codigo": v.codigo, "ok": False,
                           "error": "El product_id no existe en Loggro."})
            continue
        cstore.vincular(app_id, req.app_name or app_id, v.codigo, v.product_id,
                        product_name=p.get("name"), nombre_origen=v.nombre_origen,
                        data=data, persistir=False)
        ocupados[v.product_id] = f"{app_id}/{cstore.normalizar_codigo(v.codigo)}"
        salida.append({"codigo": v.codigo, "ok": True, "product_id": v.product_id,
                       "product_name": p.get("name")})
    try:
        cstore.guardar(data)
    except Exception as e:
        raise HTTPException(502, f"No se pudieron guardar los vínculos: {e}")
    return {"app": app_id, "ok": all(s["ok"] for s in salida), "resultados": salida}


@router.delete("/vinculos/{codigo}")
def borrar_vinculo(codigo: str, app_id: str = Depends(app_actual)):
    """Rompe la homologación de un código. **No toca el producto en Loggro.**"""
    if not cstore.vinculo(app_id, codigo):
        raise HTTPException(404, f"El código '{codigo}' no está vinculado.")
    try:
        cstore.desvincular(app_id, codigo)
    except Exception as e:
        raise HTTPException(502, f"No se pudo eliminar el vínculo: {e}")
    return {"ok": True, "codigo": codigo}


# --------------------------------------------------------------------------- #
# Endpoints — escritura (app -> Loggro)
# --------------------------------------------------------------------------- #
def _upsert_uno(app_id: str, p: ProductoIn, crear_faltantes: bool,
                location_id: Optional[str], data: dict) -> dict:
    """Crea o actualiza un producto. Devuelve el resultado de esa línea."""
    v = cstore.vinculo(app_id, p.codigo, data)
    aviso = None
    cat_id = None
    if p.categoria is not None or v is None:
        cat_id, aviso = _resolver_categoria(p.categoria)

    # --- ya homologado: read-modify-write ---
    if v:
        try:
            prod, hubo = _aplicar_cambios(v["product_id"], p.nombre, p.precio, p.activo,
                                          p.descripcion, cat_id if p.categoria else None,
                                          location_id)
        except HTTPException as e:
            return {"codigo": p.codigo, "accion": "error", "product_id": v["product_id"],
                    "error": e.detail}
        except Exception as e:
            return {"codigo": p.codigo, "accion": "error", "product_id": v["product_id"],
                    "error": str(e)}
        vista = _vista(prod)
        cstore.marcar_push(app_id, p.codigo, vista["nombre"], vista["precio"], vista["activo"],
                           product_name=vista["nombre"], data=data, persistir=False)
        return {"codigo": p.codigo, "accion": "actualizado" if hubo else "sin_cambios",
                "product_id": v["product_id"], "producto": vista,
                **({"advertencia": aviso} if aviso else {})}

    # --- no homologado ---
    if not crear_faltantes:
        return {"codigo": p.codigo, "accion": "omitido",
                "error": "El código no está vinculado y crear_faltantes=false. "
                         "Homológalo con POST /api/catalogo/vinculos."}
    if not (p.nombre or "").strip():
        return {"codigo": p.codigo, "accion": "error",
                "error": "Para crear el producto hace falta el nombre."}
    try:
        creado = _crear_en_loggro(p.nombre.strip(), p.precio or 0, cat_id,
                                  p.descripcion or "", True if p.activo is None else p.activo,
                                  location_id, p.descontar_inventario)
    except Exception as e:
        return {"codigo": p.codigo, "accion": "error", "error": f"Loggro rechazó la creación: {e}"}
    _invalidar_cache()
    vista = _vista(creado)
    cstore.vincular(app_id, app_id, p.codigo, creado["_id"], product_name=vista["nombre"],
                    nombre_origen=p.nombre, creado_por_api=True, data=data, persistir=False)
    cstore.marcar_push(app_id, p.codigo, vista["nombre"], vista["precio"], vista["activo"],
                       data=data, persistir=False)
    return {"codigo": p.codigo, "accion": "creado", "product_id": creado["_id"],
            "producto": vista, **({"advertencia": aviso} if aviso else {})}


@router.post("/productos")
def upsert_productos(req: UpsertRequest, app_id: str = Depends(app_actual)):
    """Sincroniza uno o varios productos de la app hacia Loggro (crear o actualizar).

    Idempotente: mandar dos veces lo mismo devuelve `sin_cambios` la segunda vez y no
    escribe en Loggro. Es el endpoint que llama Apptender cuando cambia un precio, un
    nombre, o cuando se crea un producto en la carta.
    """
    if not req.productos:
        raise HTTPException(400, "No se enviaron productos.")
    if len(req.productos) > 500:
        raise HTTPException(400, "Máximo 500 productos por llamada.")

    data = cstore.cargar()
    resultados = [_upsert_uno(app_id, p, req.crear_faltantes, req.location_id, data)
                  for p in req.productos]
    try:
        cstore.guardar(data)
    except Exception as e:
        raise HTTPException(502, f"Los cambios se aplicaron en Loggro pero no se pudo "
                                 f"guardar la homologación: {e}")
    resumen: dict[str, int] = {}
    for r in resultados:
        resumen[r["accion"]] = resumen.get(r["accion"], 0) + 1
    return {"app": app_id, "total": len(resultados), "resumen": resumen, "resultados": resultados}


@router.patch("/productos/{codigo}")
def patch_producto(codigo: str, req: CambioIn, app_id: str = Depends(app_actual)):
    """Cambio puntual sobre un producto ya vinculado (precio, nombre, activo...)."""
    data = cstore.cargar()
    v = cstore.vinculo(app_id, codigo, data)
    if not v:
        raise HTTPException(404, f"El código '{codigo}' no está vinculado. Usa POST "
                                 f"/api/catalogo/productos o /api/catalogo/vinculos primero.")
    cat_id, aviso = (_resolver_categoria(req.categoria) if req.categoria else (None, None))
    try:
        prod, hubo = _aplicar_cambios(v["product_id"], req.nombre, req.precio, req.activo,
                                      req.descripcion, cat_id, req.location_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Error actualizando en Loggro: {e}")
    vista = _vista(prod)
    cstore.marcar_push(app_id, codigo, vista["nombre"], vista["precio"], vista["activo"],
                       product_name=vista["nombre"], data=data)
    return {"ok": True, "codigo": codigo, "accion": "actualizado" if hubo else "sin_cambios",
            "producto": vista, **({"advertencia": aviso} if aviso else {})}


@router.delete("/productos/{codigo}")
def quitar_producto(codigo: str, borrar: bool = Query(False, description="true = borrar de Loggro; "
                                                      "por defecto solo se desactiva"),
                    app_id: str = Depends(app_actual)):
    """Saca un producto de la carta. Por defecto lo **desactiva** (isActive=false),
    que es lo correcto cuando 'ya no sale': conserva el histórico de ventas.
    Con `?borrar=true` lo elimina de Loggro y rompe el vínculo.
    """
    data = cstore.cargar()
    v = cstore.vinculo(app_id, codigo, data)
    if not v:
        raise HTTPException(404, f"El código '{codigo}' no está vinculado.")
    if borrar:
        try:
            loggro_session.cliente().delete_product(v["product_id"])
        except Exception as e:
            raise HTTPException(502, f"Error eliminando el producto en Loggro: {e}")
        _invalidar_cache()
        cstore.desvincular(app_id, codigo, data=data)
        return {"ok": True, "codigo": codigo, "accion": "eliminado",
                "product_id": v["product_id"]}
    try:
        prod, hubo = _aplicar_cambios(v["product_id"], None, None, False, None, None, None)
    except Exception as e:
        raise HTTPException(502, f"Error desactivando el producto en Loggro: {e}")
    vista = _vista(prod)
    cstore.marcar_push(app_id, codigo, vista["nombre"], vista["precio"], vista["activo"],
                       data=data)
    return {"ok": True, "codigo": codigo,
            "accion": "desactivado" if hubo else "ya_estaba_desactivado", "producto": vista}


# --------------------------------------------------------------------------- #
# Endpoint — flujo inverso (Loggro -> app)
# --------------------------------------------------------------------------- #
@router.get("/cambios")
def cambios(desde: Optional[str] = Query(None, description="ISO 8601. Solo cambios posteriores."),
            incluir_eco: bool = Query(False, description="true = incluir también los cambios "
                                                         "que hizo esta misma API."),
            app_id: str = Depends(app_actual)):
    """Qué cambió en Loggro para los productos de esta app (sondeo, no hay webhooks).

    La app guarda el `consultado_en` de la respuesta y lo manda como `desde` la próxima
    vez. Los cambios que hizo esta misma API se descartan comparando contra la huella
    `last_push`, para que un push no rebote como si fuera un cambio del POS.
    """
    try:
        prods = _productos_loggro(refresh=True)
    except Exception as e:
        raise HTTPException(502, f"Error consultando productos en Loggro: {e}")

    corte = None
    if desde:
        try:
            corte = dt.datetime.fromisoformat(desde.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, f"Fecha 'desde' inválida: {desde!r}. Usa ISO 8601.")
        if corte.tzinfo is None:
            corte = corte.replace(tzinfo=dt.timezone.utc)

    por_id = {p.get("_id"): p for p in prods}
    salida = []
    for cod, e in cstore.app_items(app_id).items():
        pid = e.get("product_id")
        p = por_id.get(pid)
        if not p:
            salida.append({"codigo": e.get("codigo", cod), "product_id": pid,
                           "estado": "eliminado_en_loggro"})
            continue
        mod = p.get("modifiedOn")
        if corte and mod:
            try:
                if dt.datetime.fromisoformat(mod.replace("Z", "+00:00")) <= corte:
                    continue
            except ValueError:
                pass
        v = _vista(p)
        lp = e.get("last_push") or {}
        campos = [k for k in ("nombre", "precio", "activo")
                  if k in lp and lp.get(k) != v[k]]
        es_eco = bool(lp) and not campos
        if es_eco and not incluir_eco:
            continue
        salida.append({"codigo": e.get("codigo", cod), "product_id": pid,
                       "estado": "modificado", "campos_distintos": campos,
                       "eco_de_esta_api": es_eco, **v})

    return {"app": app_id, "desde": desde,
            "consultado_en": cstore.ahora(), "total": len(salida), "cambios": salida}
