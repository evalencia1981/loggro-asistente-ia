"""
backend/app.py — API FastAPI para la homologación de compras Loggro.

Reutiliza loggro_client.py (toda la lógica de Loggro en un solo lugar) y
homologacion_store.py (almacén por proveedor + descripción).

Cachea productos y proveedores en memoria para no golpear la API de Loggro en
cada request. Se refresca bajo demanda (?refresh=true) o con POST /api/cache/refresh.

Correr:  uvicorn backend.app:app --reload --port 8090   (desde la raíz del proyecto)
         El puerto sale de ports.json; ver docs/PUERTOS.md.
"""
from __future__ import annotations

import os
import sys
import time
import datetime as dt
import unicodedata
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Importar módulos del proyecto (están en la raíz, un nivel arriba)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loggro_client import LoggroClient, LOCATION_STOCK_ID  # noqa: E402
import loggro_session  # noqa: E402  (cliente Loggro compartido)
import homologacion_store as store  # noqa: E402
import loggro_intake  # noqa: E402  (extractor + chat reutilizables)
import informe_creditos  # noqa: E402  (agrupación de cartera, compartida con el CSV)
from backend.catalogo_api import router as catalogo_router  # noqa: E402

app = FastAPI(title="Loggro Homologación API", version="1.0.0")

# Orígenes permitidos: el frontend local + los que se agreguen por entorno
# (CORS_ORIGINS="https://apptender.com,https://otra.app") para que las apps externas
# puedan llamar la API de catálogo desde el navegador. Las llamadas servidor-a-servidor
# no pasan por CORS.
def _puerto_web() -> int:
    """Puerto del frontend, desde ports.json (misma fuente que start.ps1 y Vite)."""
    try:
        import json as _json
        ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ports.json")
        with open(ruta, encoding="utf-8") as f:
            return int(_json.load(f)["web"])
    except Exception:
        return 8091


_ORIGENES = [f"http://localhost:{_puerto_web()}", f"http://127.0.0.1:{_puerto_web()}"] + [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGENES,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API de carta/catálogo para apps externas (Apptender, etc.) -> /api/catalogo/*
app.include_router(catalogo_router)

# --------------------------------------------------------------------------- #
# Estado / caché
# --------------------------------------------------------------------------- #
# Caché en memoria. Se auto-refresca al pasar el TTL; o manualmente vía /api/cache/refresh.
CACHE_TTL = 600  # segundos (10 min)
_cache: dict[str, Any] = {
    "products": None, "providers": None,
    "products_ts": 0.0, "providers_ts": 0.0,
    "tipos_gasto": None, "responsables": None,
    "tipos_gasto_ts": 0.0, "responsables_ts": 0.0,
}


def cliente() -> LoggroClient:
    """Cliente Loggro compartido (un solo login por proceso, ver loggro_session.py)."""
    return loggro_session.cliente()


def _expirado(ts: float) -> bool:
    return (time.time() - ts) > CACHE_TTL


def _sin_acentos(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _fecha_iso(fecha: Optional[str]) -> str:
    """Normaliza la fecha de la factura a ISO (YYYY-MM-DD).

    La factura puede traerla en DD/MM/YYYY (Colombia), ISO, etc. Loggro exige ISO;
    una fecha mal formada hace que /inventories devuelva 500. Si no se puede parsear,
    usa la fecha de hoy.
    """
    s = (fecha or "").strip()
    if not s:
        return dt.date.today().isoformat()
    # ¿ya viene ISO (YYYY-MM-DD, con o sin hora)?
    try:
        return dt.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        pass
    # Formatos comunes (Colombia = día/mes/año)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return dt.date.today().isoformat()


def _nit_base(doc: str) -> str:
    """NIT sin dígito de verificación ni formato: parte antes de '-', solo dígitos."""
    base = (doc or "").split("-")[0]
    return "".join(c for c in base if c.isdigit())


def _homolog_key(provider_id: str) -> str:
    """Clave de homologación por proveedor REAL (NIT base), para que NO se divida
    entre proveedores duplicados con el mismo NIT. Fallback: el propio id."""
    try:
        for p in cargar_proveedores():
            if p["id"] == provider_id:
                base = _nit_base(p.get("document") or "")
                return f"nit:{base}" if base else provider_id
    except Exception:
        pass
    return provider_id


def cargar_productos(refresh: bool = False) -> list[dict]:
    if _cache["products"] is None or refresh or _expirado(_cache["products_ts"]):
        prods = cliente().get_products()
        _cache["products"] = [
            {"id": p.get("_id"), "name": p.get("name") or "",
             "_search": _sin_acentos(p.get("name") or "")}
            for p in prods
        ]
        _cache["products_ts"] = time.time()
    return _cache["products"]


def cargar_proveedores(refresh: bool = False) -> list[dict]:
    if _cache["providers"] is None or refresh or _expirado(_cache["providers_ts"]):
        provs = cliente().get_providers()
        _cache["providers"] = [
            {"id": p.get("_id"), "name": p.get("name") or "",
             "document": p.get("document") or ""}
            for p in provs
        ]
        _cache["providers_ts"] = time.time()
    return _cache["providers"]


def cargar_tipos_gasto(refresh: bool = False) -> list[dict]:
    if _cache["tipos_gasto"] is None or refresh or _expirado(_cache["tipos_gasto_ts"]):
        tipos = cliente().get_type_expenses()
        _cache["tipos_gasto"] = [
            {"id": t.get("_id"), "name": t.get("name") or ""} for t in tipos
        ]
        _cache["tipos_gasto_ts"] = time.time()
    return _cache["tipos_gasto"]


def cargar_responsables(refresh: bool = False) -> list[dict]:
    if _cache["responsables"] is None or refresh or _expirado(_cache["responsables_ts"]):
        users = cliente().get_users()
        _cache["responsables"] = [
            {"id": u.get("_id"),
             "name": (f"{u.get('name', '')} {u.get('lastName', '')}").strip() or "—"}
            for u in users
        ]
        _cache["responsables_ts"] = time.time()
    return _cache["responsables"]


def cache_status() -> dict:
    now = time.time()
    return {
        "products": len(_cache["products"] or []),
        "providers": len(_cache["providers"] or []),
        "products_age": None if not _cache["products_ts"] else round(now - _cache["products_ts"]),
        "providers_age": None if not _cache["providers_ts"] else round(now - _cache["providers_ts"]),
        "ttl": CACHE_TTL,
    }


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class ItemTirilla(BaseModel):
    descripcion: str
    cantidad: Optional[float] = None
    total: Optional[float] = None


class CheckRequest(BaseModel):
    provider_id: str
    items: list[ItemTirilla]


class AssignRequest(BaseModel):
    provider_id: str
    provider_name: Optional[str] = None
    descripcion: str
    product_id: str
    product_name: Optional[str] = None
    factor: float = 1  # unidades de inventario por unidad facturada (six pack = 6)


class UnassignRequest(BaseModel):
    provider_id: str
    descripcion: str


class MovItem(BaseModel):
    descripcion: str
    product_id: str
    cantidad: float
    total: float  # total de la línea (con impuestos)
    factor: float = 1  # unidades de inventario por unidad facturada


class CrearMovRequest(BaseModel):
    provider_id: str
    invoice_number: str = ""
    fecha: Optional[str] = None  # YYYY-MM-DD; si falta, hoy
    pagado: bool = False
    nota: str = ""
    items: list[MovItem]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/providers")
def get_providers(refresh: bool = Query(False)):
    try:
        return cargar_proveedores(refresh)
    except Exception as e:
        raise HTTPException(502, f"Error consultando proveedores en Loggro: {e}")


@app.get("/api/products")
def get_products(q: Optional[str] = None, limit: int = 50, refresh: bool = Query(False)):
    try:
        prods = cargar_productos(refresh)
    except Exception as e:
        raise HTTPException(502, f"Error consultando productos en Loggro: {e}")
    if q:
        needle = _sin_acentos(q)
        prods = [p for p in prods if needle in p["_search"]]
    return [{"id": p["id"], "name": p["name"]} for p in prods[:limit]]


@app.post("/api/homologacion/check")
def check(req: CheckRequest):
    """Para cada ítem de la tirilla, dice si ya está homologado (y a qué producto)."""
    data = store.cargar()
    key = _homolog_key(req.provider_id)
    prov_items = data["providers"].get(key, {}).get("items", {})
    resultado = []
    reconocidos = 0
    for it in req.items:
        entry = prov_items.get(store.normalizar(it.descripcion))
        pid = entry["product_id"] if entry else None
        if pid:
            reconocidos += 1
        resultado.append({
            "descripcion": it.descripcion,
            "cantidad": it.cantidad,
            "total": it.total,
            "reconocido": bool(pid),
            "product_id": pid,
            "product_name": (entry or {}).get("product_name") if entry else None,
            "factor": (entry or {}).get("factor", 1) if entry else 1,
        })
    return {
        "provider_id": req.provider_id,
        "total": len(req.items),
        "reconocidos": reconocidos,
        "pendientes": len(req.items) - reconocidos,
        "items": resultado,
    }


@app.post("/api/homologacion/assign")
def assign(req: AssignRequest):
    name = req.product_name
    if not name:
        prods = cargar_productos()
        match = next((p for p in prods if p["id"] == req.product_id), None)
        name = match["name"] if match else None
    key = _homolog_key(req.provider_id)
    try:
        store.asignar(key, req.provider_name or "", req.descripcion,
                      req.product_id, name, factor=req.factor or 1)
    except Exception as e:
        raise HTTPException(502, f"No se pudo guardar la homologación: {e}")
    return {"ok": True, "descripcion": req.descripcion,
            "product_id": req.product_id, "product_name": name, "factor": req.factor or 1}


@app.post("/api/homologacion/unassign")
def unassign(req: UnassignRequest):
    try:
        store.eliminar(_homolog_key(req.provider_id), req.descripcion)
    except Exception as e:
        raise HTTPException(502, f"No se pudo eliminar la homologación: {e}")
    return {"ok": True}


@app.get("/api/homologacion")
def get_homologacion():
    return store.cargar()


@app.get("/api/cache/status")
def get_cache_status():
    """Cuántos productos/proveedores hay en caché y hace cuánto se sincronizaron."""
    return cache_status()


@app.post("/api/cache/refresh")
def post_cache_refresh():
    """Fuerza traer productos y proveedores frescos desde Loggro (sincronizar)."""
    try:
        cargar_productos(refresh=True)
        cargar_proveedores(refresh=True)
    except Exception as e:
        raise HTTPException(502, f"Error sincronizando con Loggro: {e}")
    return cache_status()


def _solo_digitos(s: str) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _match_catalogo(texto: str, items: list[dict]) -> Optional[str]:
    """Cruza un texto dictado (ej. 'arriendo', 'Edward Valencia') con un catálogo
    [{id, name}] y devuelve el id del mejor match, o None."""
    t = _sin_acentos(texto)
    if not t:
        return None
    nombres = [(it.get("id"), _sin_acentos(it.get("name") or "")) for it in items]
    for cid, n in nombres:          # match exacto
        if n and n == t:
            return cid
    for cid, n in nombres:          # uno contiene al otro
        if n and (t in n or n in t):
            return cid
    tokens = [w for w in t.split() if len(w) > 2]
    for cid, n in nombres:          # solape de palabras significativas
        ntoks = n.split()
        if any(w in ntoks for w in tokens):
            return cid
    return None


def _sugerir_catalogos_gasto(g: dict) -> tuple[Optional[str], Optional[str]]:
    """Devuelve (tipo_gasto_id, responsable_id) sugeridos a partir del texto del gasto."""
    try:
        tipo = _match_catalogo(g.get("tipo_gasto", ""), cargar_tipos_gasto())
    except Exception:
        tipo = None
    try:
        resp = _match_catalogo(g.get("responsable", ""), cargar_responsables())
    except Exception:
        resp = None
    return tipo, resp


def _sugerir_proveedor(extraccion: dict) -> Optional[dict]:
    """Busca un proveedor existente cuyo NIT coincida con el de la factura.

    Determinista: primero match exacto de dígitos; si no, por NIT base (sin DV),
    para que con proveedores duplicados siempre se elija el mismo.
    """
    nit = _solo_digitos((extraccion.get("proveedor") or {}).get("nit", ""))
    if not nit:
        return None
    provs = cargar_proveedores()
    for p in provs:  # match exacto (incluye DV si lo trae la factura)
        if _solo_digitos(p["document"]) == nit:
            return p
    base = _nit_base(nit)
    for p in provs:  # match por NIT base (ignora el dígito de verificación)
        if _nit_base(p["document"]) == base:
            return p
    return None


@app.post("/api/extraer")
async def extraer(file: UploadFile = File(...)):
    """Sube la foto de una tirilla -> Claude (visión) extrae proveedor, ítems y totales.

    Devuelve la extracción (sección 4.1 del spec) + un proveedor sugerido por NIT.
    """
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(400, "Falta GEMINI_API_KEY en el .env para extraer con IA.")
    try:
        import extractor  # import diferido: solo se necesita aquí
    except ImportError as e:
        raise HTTPException(500, f"No se pudo cargar el extractor: {e}")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío.")
    media = extractor.media_type_from_name(file.filename or "tirilla.jpg")
    try:
        extraccion = extractor.extraer_tirilla(data, media)
    except Exception as e:
        raise HTTPException(502, f"Error extrayendo la tirilla: {e}")

    # Sugerir proveedor existente por NIT (comparando solo dígitos)
    proveedor_sugerido = _sugerir_proveedor(extraccion)

    return {"extraccion": extraccion, "proveedor_sugerido": proveedor_sugerido}


# --------------------------------------------------------------------------- #
# Captura por chat (lenguaje natural / dictado) -> misma factura
# --------------------------------------------------------------------------- #
class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    mensaje: str
    factura: Optional[dict] = None      # estado actual de la factura
    historial: list[ChatTurn] = []      # contexto opcional


class GastoChatRequest(BaseModel):
    mensaje: str
    gasto: Optional[dict] = None
    historial: list[ChatTurn] = []


class CrearGastoRequest(BaseModel):
    type_expense_id: str                # tipo de gasto (obligatorio)
    paid_to_id: Optional[str] = None    # responsable
    provider_id: Optional[str] = None
    invoice_number: str = ""
    forma_pago: str = ""
    concepto: str                       # description (obligatorio)
    notas: str = ""
    subtotal: float = 0
    impuestos: float = 0
    sale_de_caja: bool = False          # subtractCashRegister
    fecha: Optional[str] = None


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Procesa un turno del chat: actualiza la factura y responde.

    Devuelve el mismo formato que /api/extraer (extraccion + proveedor_sugerido)
    más una `respuesta` en lenguaje natural para mostrar en el chat.
    """
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(400, "Falta GEMINI_API_KEY en el .env para el chat con IA.")
    if not (req.mensaje or "").strip():
        raise HTTPException(400, "Mensaje vacío.")
    try:
        out = loggro_intake.conversar(
            req.mensaje,
            factura=req.factura,
            historial=[t.model_dump() for t in req.historial],
        )
    except Exception as e:
        raise HTTPException(502, f"Error en el chat con IA: {e}")

    factura = out.get("factura") or {}
    return {
        "extraccion": factura,
        "proveedor_sugerido": _sugerir_proveedor(factura),
        "respuesta": out.get("respuesta", ""),
    }


# --------------------------------------------------------------------------- #
# Crear el movimiento de compra en Loggro (POST /inventories)
# --------------------------------------------------------------------------- #
_tipo_compra_id: Optional[int] = None


def _tipo_compra() -> int:
    """Resuelve (y cachea) el id del tipo 'Entrada - Compra'. Fallback: 1."""
    global _tipo_compra_id
    if _tipo_compra_id is None:
        try:
            _tipo_compra_id = cliente().get_tipo_compra_id()
        except Exception:
            _tipo_compra_id = 1  # confirmado en la cuenta Virus Pub
    return _tipo_compra_id


@app.post("/api/movimiento")
def crear_movimiento(req: CrearMovRequest):
    """Crea la compra (Entrada - Compra) en Loggro a partir de los ítems homologados.

    Construye el payload (mismo esquema que loggro_client.construir_movimiento),
    valida y hace POST /inventories. Devuelve el _id del movimiento creado.
    """
    if not req.items:
        raise HTTPException(400, "No hay ítems para registrar.")

    detalles = []
    total = 0.0
    for it in req.items:
        if not it.product_id:
            raise HTTPException(400, f"El ítem '{it.descripcion}' no está homologado.")
        # Conversión empaque->unidad: 1 six pack facturado = 6 unidades en inventario.
        cant_real = (it.cantidad or 0) * (it.factor or 1)
        if cant_real <= 0:
            raise HTTPException(400, f"Cantidad inválida para '{it.descripcion}'.")
        detalles.append({
            "ingredient": it.product_id,
            "quantity": cant_real,                      # unidades reales a inventario
            "price": round(it.total / cant_real),       # costo unitario por unidad real
            "locationStock": LOCATION_STOCK_ID,
            "note": "",
        })
        total += it.total

    fecha = _fecha_iso(req.fecha)
    payload = {
        "date": f"{fecha}T00:00:00.000Z",
        "type": _tipo_compra(),
        "provider": req.provider_id,
        "note": req.nota.strip(),
        "total": total,
        "invoice": {
            "invoiceNumber": req.invoice_number,
            "isPaid": req.pagado,
            "total": total,
        },
        "ingredients": detalles,
    }

    try:
        resp = cliente().create_movement(payload)
    except Exception as e:
        # Log del payload para diagnosticar qué ítem rechaza Loggro.
        import json as _json
        print("[crear_movimiento] FALLO. Payload enviado:")
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        print("[crear_movimiento] Error Loggro:", e)
        raise HTTPException(502, f"Error creando el movimiento en Loggro: {e}")

    return {
        "ok": True,
        "movement_id": resp.get("_id") if isinstance(resp, dict) else None,
        "invoice_number": req.invoice_number,
        "total": total,
        "items": len(detalles),
    }


@app.delete("/api/movimiento/{movement_id}")
def eliminar_movimiento(movement_id: str):
    """Revierte una compra: DELETE /inventories/{_id} (deshace stock y avgCost)."""
    try:
        resp = cliente().delete_movement(movement_id)
    except Exception as e:
        raise HTTPException(502, f"Error eliminando el movimiento en Loggro: {e}")
    return {"ok": True, "movement_id": movement_id, "raw": resp}


# --------------------------------------------------------------------------- #
# Módulo de GASTOS (POST/GET/DELETE /expenses) — reutiliza foto + chat
# --------------------------------------------------------------------------- #
@app.get("/api/gastos/tipos")
def gastos_tipos(refresh: bool = Query(False)):
    """Catálogo de tipos de gasto (dropdown 'Tipo de gasto')."""
    try:
        return cargar_tipos_gasto(refresh)
    except Exception as e:
        raise HTTPException(502, f"Error consultando tipos de gasto: {e}")


@app.get("/api/gastos/responsables")
def gastos_responsables(refresh: bool = Query(False)):
    """Catálogo de responsables/usuarios (dropdown 'Responsable')."""
    try:
        return cargar_responsables(refresh)
    except Exception as e:
        raise HTTPException(502, f"Error consultando responsables: {e}")


@app.post("/api/gastos/extraer")
async def gastos_extraer(file: UploadFile = File(...)):
    """Foto de un recibo de gasto -> datos del gasto + proveedor sugerido por NIT."""
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(400, "Falta GEMINI_API_KEY en el .env para extraer con IA.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío.")
    media = loggro_intake.media_type_from_name(file.filename or "gasto.jpg")
    try:
        g = loggro_intake.extraer_gasto(data, media)
    except Exception as e:
        raise HTTPException(502, f"Error extrayendo el gasto: {e}")
    tipo_id, resp_id = _sugerir_catalogos_gasto(g)
    return {
        "gasto": g,
        "proveedor_sugerido": _sugerir_proveedor(g),
        "tipo_sugerido": tipo_id,
        "responsable_sugerido": resp_id,
    }


@app.post("/api/gastos/chat")
def gastos_chat(req: GastoChatRequest):
    """Turno de chat (texto/voz) para armar un gasto."""
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(400, "Falta GEMINI_API_KEY en el .env para el chat con IA.")
    if not (req.mensaje or "").strip():
        raise HTTPException(400, "Mensaje vacío.")
    try:
        out = loggro_intake.conversar_gasto(
            req.mensaje, gasto=req.gasto,
            historial=[t.model_dump() for t in req.historial],
        )
    except Exception as e:
        raise HTTPException(502, f"Error en el chat con IA: {e}")
    g = out.get("gasto") or {}
    tipo_id, resp_id = _sugerir_catalogos_gasto(g)
    return {
        "gasto": g,
        "proveedor_sugerido": _sugerir_proveedor(g),
        "tipo_sugerido": tipo_id,
        "responsable_sugerido": resp_id,
        "respuesta": out.get("respuesta", ""),
    }


@app.post("/api/gastos")
def crear_gasto(req: CrearGastoRequest):
    """Registra el gasto en Loggro (POST /expenses)."""
    if not (req.concepto or "").strip():
        raise HTTPException(400, "El concepto del gasto es obligatorio.")
    if not req.type_expense_id:
        raise HTTPException(400, "El tipo de gasto es obligatorio.")

    body: dict[str, Any] = {
        "typeExpense": req.type_expense_id,
        "description": req.concepto.strip(),
        "invoiceNumber": req.invoice_number or "",
        "paymentMethod": req.forma_pago or "",
        "notes": req.notas or "",
        "subTotal": req.subtotal or 0,
        "taxes": req.impuestos or 0,
        "subtractCashRegister": bool(req.sale_de_caja),
        "date": f"{_fecha_iso(req.fecha)}T00:00:00.000Z",
    }
    if req.paid_to_id:
        body["paidTo"] = req.paid_to_id
    if req.provider_id:
        body["provider"] = req.provider_id
    if req.sale_de_caja:
        box = cliente().get_active_cashbox()
        if not box:
            raise HTTPException(400, "No hay caja abierta; no se puede marcar 'Sale de caja'.")
        body["cashBox"] = box.get("_id")

    try:
        resp = cliente().create_expense(body)
    except Exception as e:
        import json as _json
        print("[crear_gasto] FALLO. Payload:")
        print(_json.dumps(body, ensure_ascii=False, indent=2))
        print("[crear_gasto] Error Loggro:", e)
        raise HTTPException(502, f"Error creando el gasto en Loggro: {e}")

    return {
        "ok": True,
        "expense_id": resp.get("_id") if isinstance(resp, dict) else None,
        "total": (req.subtotal or 0) + (req.impuestos or 0),
    }


@app.delete("/api/gastos/{expense_id}")
def eliminar_gasto(expense_id: str):
    """Elimina (soft delete) un gasto: DELETE /expenses/{_id}."""
    try:
        cliente().delete_expense(expense_id)
    except Exception as e:
        raise HTTPException(502, f"Error eliminando el gasto en Loggro: {e}")
    return {"ok": True, "expense_id": expense_id}


# --------------------------------------------------------------------------- #
# Cartera (créditos / fiados de clientes)
# --------------------------------------------------------------------------- #
@app.get("/api/creditos")
def get_creditos(desde: str = "2020-01-01", hasta: Optional[str] = None):
    """Deuda por cliente: facturas a crédito pendientes, agrupadas y con antigüedad.

    La lógica de agrupación vive en `informe_creditos.py` (mismo cálculo que el
    informe de consola y el CSV) para que las cifras no se puedan desincronizar.
    """
    hoy = dt.date.today()
    fin = dt.date.fromisoformat(hasta) if hasta else hoy
    try:
        cli = cliente()
        facturas = cli.get_credit_invoices(
            f"{desde}T00:00:00.000Z",
            f"{(fin + dt.timedelta(days=1)).isoformat()}T00:00:00.000Z",
        )
        crudo = cli._get("/clients")
        catalogo = {c["_id"]: c for c in (crudo.get("data", crudo) if isinstance(crudo, dict) else crudo)}
    except Exception as e:
        raise HTTPException(502, f"Error consultando los créditos en Loggro: {e}")

    filas = informe_creditos.agrupar(facturas, hoy, catalogo)
    return {
        "generado": hoy.isoformat(),
        "desde": desde,
        "hasta": fin.isoformat(),
        "saldo": sum(f["saldo"] for f in filas),
        "facturado": sum(f["total"] for f in filas),
        "abonado": sum(f["abonado"] for f in filas),
        "clientes": len(filas),
        "facturas": sum(f["facturas"] for f in filas),
        "tramos": [
            {"etiqueta": etiqueta, "monto": sum(f["tramos"].get(etiqueta, 0) for f in filas)}
            for etiqueta, _, _ in informe_creditos.TRAMOS
        ],
        "detalle": filas,
    }
