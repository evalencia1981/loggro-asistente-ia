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
import re
import sys
import time
import datetime as dt
import unicodedata
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Importar módulos del proyecto (están en la raíz, un nivel arriba)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from loggro_client import LoggroClient, LOCATION_STOCK_ID  # noqa: E402
import loggro_session  # noqa: E402  (cliente Loggro compartido)
import homologacion_store as store  # noqa: E402
import loggro_intake  # noqa: E402  (extractor + chat reutilizables)
import informe_creditos  # noqa: E402  (agrupación de cartera, compartida con el CSV)
import recurrentes_store  # noqa: E402  (beneficiarios recurrentes de gastos)
import informe_utilidad  # noqa: E402  (utilidad: ventas vs compras+gastos)
import movimientos_inventario as mov_inv  # noqa: E402  (ajustes, mermas, conteo físico)
import informe_stock  # noqa: E402  (existencias y sugerido de pedido)
import acceso  # noqa: E402  (puerta de acceso: usuarios, roles, código maestro)
import usuarios_store  # noqa: E402  (usuarios con contraseña y rol)
from backend.catalogo_api import router as catalogo_router  # noqa: E402

# /docs y /openapi.json enumeran todos los endpoints y sus payloads: es un mapa
# para quien no debería estar. Solo se exponen fuera de producción.
_EN_VERCEL = bool(os.getenv("VERCEL"))
app = FastAPI(
    title="Loggro Homologación API", version="1.0.0",
    docs_url=None if _EN_VERCEL else "/docs",
    redoc_url=None,
    openapi_url=None if _EN_VERCEL else "/openapi.json",
)

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
# Puerta de acceso
# --------------------------------------------------------------------------- #
@app.middleware("http")
async def puerta_de_acceso(request: Request, call_next):
    """Valida el código ANTES de llegar a cualquier handler.

    Tiene que estar aquí y no en el frontend: esconder pestañas en React no
    protege nada, los endpoints se llaman igual con curl. Antes de esto,
    cualquiera con la URL leía la cartera (cédulas y celulares de los clientes)
    y podía crear gastos reales en Loggro.
    """
    ruta = request.url.path
    if request.method == "OPTIONS" or acceso.ruta_abierta(ruta):
        return await call_next(request)

    if not acceso.configurado():
        return JSONResponse(
            {"detail": "El acceso no está configurado: falta ACCESO_CODIGO en el entorno."},
            status_code=503,
        )

    # El header sirve para scripts y curl; la cookie, para el navegador.
    sesion = acceso.sesion_de_token(_token(request))
    if not sesion:
        return JSONResponse({"detail": "Se necesita iniciar sesión.",
                             "codigo_requerido": True}, status_code=401)
    modo = sesion["modo"]

    if modo == acceso.MODO_DEMO and request.method in acceso.ESCRITURA:
        return JSONResponse(
            {"detail": "El modo demo es de solo lectura: no escribe en Loggro.",
             "modo": modo}, status_code=403)

    modulo = acceso.modulo_de_ruta(ruta)
    if modulo and modulo not in sesion["modulos"]:
        return JSONResponse(
            {"detail": f"Tu rol ({sesion['rol_nombre']}) no tiene acceso a {modulo}.",
             "modulo": modulo}, status_code=403)

    request.state.modo = modo
    request.state.sesion = sesion
    respuesta = await call_next(request)
    respuesta.headers["X-Modo"] = modo
    return respuesta


def _token(request: Request) -> str | None:
    return request.headers.get("X-Acceso") or request.cookies.get(acceso.COOKIE)


def _poner_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        acceso.COOKIE, token,
        max_age=acceso.DURACION,
        httponly=True,            # que el JS de la página no pueda leerla
        secure=_EN_VERCEL,        # en local se sirve por http
        samesite="lax",
    )


class AccesoRequest(BaseModel):
    usuario: str = ""  # vacío = la clave es el código maestro
    clave: str = ""
    codigo: str = ""   # compatibilidad con el login anterior (solo código)


def _ip(request: Request) -> str:
    """IP del visitante. Detrás de Vercel la real viene en X-Forwarded-For."""
    reenviada = request.headers.get("x-forwarded-for", "")
    return reenviada.split(",")[0].strip() or (request.client.host if request.client else "?")


@app.get("/api/acceso")
def estado_acceso(request: Request):
    """¿Esta sesión ya está adentro, quién es y qué módulos ve?"""
    sesion = acceso.sesion_de_token(_token(request))
    return {
        "dentro": bool(sesion),
        "modo": sesion["modo"] if sesion else None,
        "sesion": sesion,
        "configurado": acceso.configurado(),
        "demo_disponible": bool(os.getenv("ACCESO_CODIGO_DEMO")),
    }


@app.post("/api/acceso")
def entrar(req: AccesoRequest, request: Request, response: Response):
    """Usuario + contraseña (o el código maestro) -> cookie firmada."""
    if not acceso.configurado():
        raise HTTPException(503, "El acceso no está configurado: falta ACCESO_CODIGO.")

    ip = _ip(request)
    if acceso.bloqueado(ip):
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")

    usuario = req.usuario.strip()
    if usuario:
        hallado = usuarios_store.verificar(usuario, req.clave)
        if not hallado:
            acceso.intento_fallido(ip)
            raise HTTPException(401, "Usuario o contraseña incorrectos.")
        nombre_usuario, datos = hallado
        token = acceso.crear_token(acceso.MODO_DUENO, nombre_usuario, datos.get("sesion"))
        usuarios_store.registrar_ingreso(nombre_usuario)
    else:
        modo = acceso.verificar_codigo(req.clave or req.codigo)
        if not modo:
            acceso.intento_fallido(ip)
            raise HTTPException(401, "Código incorrecto.")
        token = acceso.crear_token(modo)

    acceso.limpiar_intentos(ip)
    _poner_cookie(response, token)
    return {"ok": True, "sesion": acceso.sesion_de_token(token)}


@app.post("/api/acceso/demo")
def entrar_demo(response: Response):
    """Demo de un clic para el portafolio: sin código, siempre solo lectura.

    Solo abre si ACCESO_CODIGO_DEMO está definido. Esa variable es el interruptor
    del demo: mientras no existan los datos ficticios se deja sin definir, para
    que un visitante no termine leyendo datos reales.
    """
    if not os.getenv("ACCESO_CODIGO_DEMO"):
        raise HTTPException(404, "El demo no está disponible.")
    token = acceso.crear_token(acceso.MODO_DEMO)
    _poner_cookie(response, token)
    return {"ok": True, "sesion": acceso.sesion_de_token(token)}


@app.post("/api/acceso/salir")
def salir(response: Response):
    response.delete_cookie(acceso.COOKIE)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Usuarios y roles (solo el rol dueño: el middleware ya filtra /api/usuarios)
# --------------------------------------------------------------------------- #
class UsuarioNuevo(BaseModel):
    usuario: str
    nombre: str = ""
    rol: str
    clave: str


class UsuarioCambio(BaseModel):
    nombre: Optional[str] = None
    rol: Optional[str] = None
    activo: Optional[bool] = None
    clave: Optional[str] = None


def _validar_rol(rol: Optional[str]) -> None:
    if rol is not None and rol not in acceso.ROLES:
        raise HTTPException(400, f"Rol desconocido: {rol}")


@app.get("/api/usuarios")
def listar_usuarios():
    return {
        "usuarios": usuarios_store.listar(),
        "roles": [{"id": k, "nombre": v["nombre"], "ayuda": v["ayuda"],
                   "modulos": acceso.modulos_de_rol(k, usar_cache=False),
                   "editable": k not in acceso.ROLES_FIJOS} for k, v in acceso.ROLES.items()],
        "modulos_asignables": list(acceso.MODULOS_ASIGNABLES),
    }


class RolCambio(BaseModel):
    modulos: list[str]


@app.put("/api/usuarios/roles/{rol}")
def cambiar_modulos_rol(rol: str, req: RolCambio):
    """El dueño elige qué módulos ve un rol. Aplica en la siguiente petición de
    quienes tengan ese rol (los módulos no van en la cookie)."""
    _validar_rol(rol)
    if rol in acceso.ROLES_FIJOS:
        raise HTTPException(400, "El rol Dueño siempre tiene todos los módulos.")
    desconocidos = [m for m in req.modulos if m not in acceso.MODULOS_ASIGNABLES]
    if desconocidos:
        raise HTTPException(400, f"Módulos no asignables: {', '.join(desconocidos)}")
    try:
        usuarios_store.guardar_modulos_de_rol(rol, req.modulos)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {"id": rol, "modulos": acceso.modulos_de_rol(rol, usar_cache=False)}


@app.post("/api/usuarios")
def crear_usuario(req: UsuarioNuevo):
    _validar_rol(req.rol)
    try:
        return usuarios_store.crear(req.usuario, req.nombre, req.rol, req.clave)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.patch("/api/usuarios/{usuario}")
def cambiar_usuario(usuario: str, req: UsuarioCambio, request: Request):
    _validar_rol(req.rol)
    yo = request.state.sesion.get("usuario")
    # Que el dueño no se quite a sí mismo el acceso a esta pantalla por error.
    if yo and usuarios_store.normalizar_usuario(usuario) == yo and (
            req.activo is False or (req.rol is not None and req.rol != "dueno")):
        raise HTTPException(400, "No puedes desactivarte ni quitarte el rol de dueño a ti mismo.")
    try:
        return usuarios_store.actualizar(usuario, nombre=req.nombre, rol=req.rol,
                                         activo=req.activo, clave=req.clave)
    except KeyError:
        raise HTTPException(404, f"No existe el usuario '{usuario}'.")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))

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


class RecurrenteRequest(BaseModel):
    """Beneficiario recurrente. Guarda lo que NO cambia entre pagos."""
    id: Optional[str] = None            # al editar; si falta se deriva del nombre
    nombre: str
    concepto: str = ""                  # vacío = se usa el nombre
    type_expense_id: str
    provider_id: Optional[str] = None
    forma_pago: str = ""
    sale_de_caja: bool = False
    monto_sugerido: int = 0
    periodicidad: str = "libre"
    activo: bool = True
    notas: str = ""


class LineaLote(BaseModel):
    """Una línea del día de pago: a quién y cuánto."""
    recurrente_id: str
    monto: int
    notas: str = ""


class LoteRequest(BaseModel):
    lineas: list[LineaLote]
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
# Otros movimientos de inventario: ajustes, mermas, devoluciones, conteo físico
# --------------------------------------------------------------------------- #
# Las listas que llegan por WhatsApp no tienen proveedor: sus símiles ("pola" ->
# Aguila Original) se aprenden en su propio grupo del almacén de homologación. El
# frontend los guarda con el mismo /api/homologacion/assign usando este id.
LISTAS_KEY = "_listas"


class ListaTextoRequest(BaseModel):
    texto: str


class LineaInventario(BaseModel):
    descripcion: str = ""
    product_id: str
    cantidad: float  # en modo conteo: lo contado; en los demás: cuánto entra/sale
    costo_unitario: Optional[float] = None  # None = el que pondría Loggro


class CrearInventarioRequest(BaseModel):
    tipo: str  # id del tipo de Loggro ("3", "6", ...) o "conteo"
    fecha: Optional[str] = None
    nota: str = ""
    items: list[LineaInventario]


def _productos_frescos() -> dict[str, dict]:
    """Productos completos de Loggro por _id, SIN caché: el stock cambia con cada venta."""
    return {p["_id"]: p for p in cliente().get_products() if p.get("_id")}


def _resolver_lista(lista: dict, productos: dict[str, dict]) -> dict:
    """Pone product_id a cada línea extraída: lo aprendido > lo que propuso la IA > parecido."""
    import difflib

    aprendidos = store.cargar()["providers"].get(LISTAS_KEY, {}).get("items", {})
    por_nombre = {_sin_acentos(p.get("name") or ""): p for p in productos.values()}
    nombres = list(por_nombre)

    items = []
    for it in lista.get("items") or []:
        desc = (it.get("descripcion") or "").strip()
        prod, origen = None, None
        entry = aprendidos.get(store.normalizar(desc))
        if entry and entry.get("product_id") in productos:
            prod, origen = productos[entry["product_id"]], "aprendido"
        if prod is None and it.get("producto_catalogo"):
            prod = por_nombre.get(_sin_acentos(it["producto_catalogo"]))
            origen = "ia" if prod else None
        if prod is None and desc:
            cerca = difflib.get_close_matches(_sin_acentos(desc), nombres, n=1, cutoff=0.75)
            if cerca:
                prod, origen = por_nombre[cerca[0]], "parecido"
        stock = mov_inv.stock_en_bodega(prod, LOCATION_STOCK_ID) if prod else None
        items.append({
            "descripcion": desc,
            "cantidad": it.get("cantidad") or 0,
            "costo_unitario": it.get("costo_unitario") or 0,
            "product_id": prod["_id"] if prod else None,
            "product_name": prod.get("name") if prod else None,
            "origen": origen,
            "stock_actual": stock["stock"] if stock else None,
        })
    return {
        "fecha": _fecha_iso(lista.get("fecha")) if lista.get("fecha") else None,
        "nota": lista.get("nota") or "",
        "items": items,
    }


@app.get("/api/inventario/tipos")
def inventario_tipos():
    """Tipos de movimiento que ofrece la app (más el modo 'conteo', que no es de Loggro)."""
    return mov_inv.TIPOS


@app.get("/api/inventario/stock")
def inventario_stock(ids: str = Query(..., description="product _id separados por coma")):
    """Stock actual en la bodega de cada producto (fresco, sin caché)."""
    productos = _productos_frescos()
    salida = {}
    for pid in [i for i in ids.split(",") if i]:
        prod = productos.get(pid)
        if prod:
            salida[pid] = mov_inv.stock_en_bodega(prod, LOCATION_STOCK_ID)
    return salida


@app.get("/api/inventario/existencias")
def inventario_existencias(dias: int = Query(15, ge=1, le=90),
                           cobertura: int = Query(7, ge=1, le=60)):
    """Por ítem: stock inicial del periodo, compras, consumo, actual y cuánto pedir.

    El cálculo vive en `informe_stock.py`, el mismo que usa la consola y el CSV.
    """
    try:
        crudos = informe_stock.traer(cliente(), dias)
    except Exception as e:
        raise HTTPException(502, f"Error consultando el inventario en Loggro: {e}")
    return informe_stock.calcular(crudos, dias, cobertura, LOCATION_STOCK_ID)


@app.post("/api/inventario/lista/texto")
def inventario_lista_texto(req: ListaTextoRequest):
    """Texto de WhatsApp -> líneas con producto sugerido y stock actual."""
    if not req.texto.strip():
        raise HTTPException(400, "La lista está vacía.")
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(400, "Falta GEMINI_API_KEY en el .env para leer la lista con IA.")
    productos = _productos_frescos()
    catalogo = [p.get("name") or "" for p in productos.values()]
    try:
        lista = loggro_intake.extraer_lista_texto(req.texto, catalogo)
    except Exception as e:
        raise HTTPException(502, f"Error leyendo la lista: {e}")
    return _resolver_lista(lista, productos)


@app.post("/api/inventario/lista/imagen")
async def inventario_lista_imagen(file: UploadFile = File(...)):
    """Foto de una lista (a mano, planilla, pantallazo) -> mismas líneas que el texto."""
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(400, "Falta GEMINI_API_KEY en el .env para leer la lista con IA.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío.")
    productos = _productos_frescos()
    catalogo = [p.get("name") or "" for p in productos.values()]
    media = loggro_intake.media_type_from_name(file.filename or "lista.jpg")
    try:
        lista = loggro_intake.extraer_lista_imagen(data, media, catalogo)
    except Exception as e:
        raise HTTPException(502, f"Error leyendo la foto: {e}")
    return _resolver_lista(lista, productos)


def _agrupar(items: list[LineaInventario]) -> list[LineaInventario]:
    """Suma las líneas del mismo producto ("aguila barra 20" + "aguila bodega 30").

    Loggro no admite el mismo producto dos veces en un movimiento. El costo que se
    conserva es el primero que venga explícito.
    """
    por_id: dict[str, LineaInventario] = {}
    for it in items:
        if it.product_id in por_id:
            prev = por_id[it.product_id]
            prev.cantidad += it.cantidad
            if prev.costo_unitario is None:
                prev.costo_unitario = it.costo_unitario
        else:
            por_id[it.product_id] = it.model_copy()
    return list(por_id.values())


def _crear_en_loggro(tipo_id: int, lineas: list[dict], fecha: str, nota: str) -> dict:
    payload = mov_inv.construir_payload(tipo_id, lineas, LOCATION_STOCK_ID, fecha, nota)
    try:
        resp = cliente().create_movement(payload)
    except Exception as e:
        import json as _json
        print("[inventario] FALLO. Payload enviado:")
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        raise HTTPException(502, f"Error creando el movimiento en Loggro: {e}")
    return {
        "movement_id": resp.get("_id") if isinstance(resp, dict) else None,
        "tipo": tipo_id,
        "tipo_nombre": mov_inv.TIPOS_POR_ID[tipo_id]["nombre"],
        "items": len(lineas),
        "total": resp.get("total") if isinstance(resp, dict) else None,
    }


@app.post("/api/inventario/movimiento")
def crear_movimiento_inventario(req: CrearInventarioRequest):
    """Crea el movimiento en Loggro (POST /inventories).

    tipo = id de Loggro: las cantidades entran o salen tal cual.
    tipo = "conteo": `cantidad` es lo CONTADO; se compara con el stock fresco y se
    generan hasta dos movimientos (Entrada-Ajuste por lo que sobra, Salida-Ajuste por
    lo que falta). Los productos que no vienen en la lista no se tocan.
    """
    if not req.items:
        raise HTTPException(400, "No hay productos para registrar.")
    if any(not it.product_id for it in req.items):
        raise HTTPException(400, "Hay productos sin homologar.")
    fecha = _fecha_iso(req.fecha)
    productos = _productos_frescos()
    items = _agrupar(req.items)
    resultado = _registrar_inventario(req, items, productos, fecha)
    _aprender_lista(req.items, productos)
    return resultado


def _aprender_lista(items: list[LineaInventario], productos: dict[str, dict]) -> None:
    """Recuerda descripcion -> producto de lo que se acaba de registrar (ya revisado por
    una persona), para que la próxima lista lo reconozca sin la IA. No falla el registro."""
    try:
        data = store.cargar()
        for it in items:
            if it.descripcion.strip() and it.product_id in productos:
                store.asignar(LISTAS_KEY, "Listas de inventario (WhatsApp)", it.descripcion,
                              it.product_id, productos[it.product_id].get("name"),
                              data=data, persistir=False)
        store.guardar(data)
    except Exception as e:
        print("[inventario] No se pudo guardar lo aprendido de la lista:", e)


def _registrar_inventario(req: CrearInventarioRequest, items: list[LineaInventario],
                          productos: dict[str, dict], fecha: str) -> dict:

    try:
        if req.tipo == "conteo":
            filas = mov_inv.diferencias_conteo(
                [{"product_id": it.product_id, "contado": it.cantidad} for it in items],
                productos, LOCATION_STOCK_ID)
            entradas, salidas = mov_inv.lineas_ajuste(filas)
            nota = req.nota.strip() or "Conteo físico"
            creados = []
            if entradas:
                creados.append(_crear_en_loggro(mov_inv.TIPO_AJUSTE_ENTRADA, entradas, fecha, nota))
            if salidas:
                creados.append(_crear_en_loggro(mov_inv.TIPO_AJUSTE_SALIDA, salidas, fecha, nota))
            return {"ok": True, "movimientos": creados, "diferencias": filas,
                    "sin_cambio": sum(1 for f in filas if f["diferencia"] == 0)}

        tipo_id = int(req.tipo)
        if tipo_id not in mov_inv.TIPOS_POR_ID:
            raise HTTPException(400, f"Tipo de movimiento no soportado: {req.tipo}")
        lineas = []
        for it in items:
            prod = productos.get(it.product_id)
            if prod is None:
                raise HTTPException(400, f"Producto no encontrado en Loggro: {it.descripcion or it.product_id}")
            costo = it.costo_unitario
            if costo is None or (costo == 0 and mov_inv.TIPOS_POR_ID[tipo_id]["costo"] != "usuario"):
                costo = mov_inv.costo_por_defecto(tipo_id, prod, LOCATION_STOCK_ID)
            lineas.append({"product_id": it.product_id, "cantidad": it.cantidad,
                           "costo_unitario": costo})
        return {"ok": True, "movimientos": [_crear_en_loggro(tipo_id, lineas, fecha, req.nota)]}
    except ValueError as e:
        raise HTTPException(400, str(e))


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


def _registrar_gasto(req: CrearGastoRequest) -> dict[str, Any]:
    """Arma el payload y crea el gasto en Loggro. Devuelve {expense_id, total}.

    Vive aparte del endpoint porque el registro por lote (día de pago) crea N
    gastos por el mismo camino: si la construcción del payload se duplicara,
    un gasto suelto y uno del lote podrían terminar guardándose distinto.
    """
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


@app.post("/api/gastos")
def crear_gasto(req: CrearGastoRequest):
    """Registra el gasto en Loggro (POST /expenses)."""
    return _registrar_gasto(req)


@app.delete("/api/gastos/{expense_id}")
def eliminar_gasto(expense_id: str):
    """Elimina (soft delete) un gasto: DELETE /expenses/{_id}."""
    try:
        cliente().delete_expense(expense_id)
    except Exception as e:
        raise HTTPException(502, f"Error eliminando el gasto en Loggro: {e}")
    return {"ok": True, "expense_id": expense_id}


# --------------------------------------------------------------------------- #
# Beneficiarios recurrentes (nómina y pagos que se repiten)
# --------------------------------------------------------------------------- #
def _aviso_persistencia(donde: Optional[str]) -> dict[str, Any]:
    """Avisa cuando un guardado se quedó en el disco local pese a haber KV.

    Sin esto el usuario cree que su lista viajó a produccion y no fue asi: el
    KV estaba configurado pero caido.
    """
    if donde == "local" and recurrentes_store.kv_disponible():
        return {"persistencia": "local", "aviso":
                "Guardado solo en este equipo: el Redis/KV no responde. "
                "Revisa REDIS_URL para que la lista viaje a produccion."}
    return {"persistencia": donde or "kv"}


def _dias_desde(iso: Optional[str]) -> Optional[int]:
    """Días transcurridos desde una fecha ISO. None si nunca se ha pagado."""
    if not iso:
        return None
    try:
        return (dt.date.today() - dt.date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


@app.get("/api/gastos/recurrentes")
def listar_recurrentes(incluir_inactivos: bool = Query(False)):
    """Lista de beneficiarios recurrentes, con el aviso de 'hace N días'.

    `vencido` es solo informativo: marca que pasó el periodo nominal desde el
    último pago. Nunca dispara la creación de un gasto — los montos varían
    demasiado como para registrarlos sin que alguien los digite.
    """
    try:
        filas = recurrentes_store.listar(incluir_inactivos=incluir_inactivos)
    except Exception as e:
        raise HTTPException(502, f"Error leyendo los recurrentes: {e}")

    for f in filas:
        dias = _dias_desde(f.get("ultimo_pago"))
        f["dias_desde_ultimo"] = dias
        periodo = recurrentes_store.DIAS_PERIODO.get(f.get("periodicidad") or "")
        f["vencido"] = bool(periodo and dias is not None and dias >= periodo)
    return {"items": filas, "total": len(filas)}


@app.post("/api/gastos/recurrentes")
def guardar_recurrente(req: RecurrenteRequest):
    """Crea o actualiza un beneficiario recurrente."""
    try:
        slug, _, donde = recurrentes_store.guardar_item(req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Error guardando el recurrente: {e}")
    return {"ok": True, "id": slug, **_aviso_persistencia(donde)}


@app.delete("/api/gastos/recurrentes/{slug}")
def eliminar_recurrente(slug: str):
    """Quita un beneficiario de la lista (no toca los gastos ya registrados)."""
    try:
        _, donde = recurrentes_store.eliminar(slug)
    except Exception as e:
        raise HTTPException(502, f"Error eliminando el recurrente: {e}")
    return {"ok": True, "id": slug, **_aviso_persistencia(donde)}


@app.post("/api/gastos/lote")
def crear_gastos_lote(req: LoteRequest):
    """Día de pago: crea UN gasto por beneficiario, no uno combinado.

    En el historial hay registros como "nomina stalle y munera (400.000 y 12…)"
    que ya no se pueden separar por persona. Por eso cada línea es su propio
    gasto, con el concepto normalizado del beneficiario.

    Una línea que falle no aborta las demás: se devuelve el detalle por línea
    para que la vista muestre qué entró y qué no.
    """
    if not req.lineas:
        raise HTTPException(400, "No hay líneas para registrar.")

    data = recurrentes_store.cargar()
    fecha = _fecha_iso(req.fecha)
    resultados: list[dict[str, Any]] = []

    for linea in req.lineas:
        item = data["items"].get(linea.recurrente_id)
        if not item:
            resultados.append({
                "recurrente_id": linea.recurrente_id, "nombre": linea.recurrente_id,
                "ok": False, "error": "El beneficiario ya no está en la lista.",
            })
            continue
        if linea.monto <= 0:
            resultados.append({
                "recurrente_id": linea.recurrente_id, "nombre": item["nombre"],
                "ok": False, "error": "El monto debe ser mayor que cero.",
            })
            continue

        gasto = CrearGastoRequest(
            type_expense_id=item["type_expense_id"],
            provider_id=item.get("provider_id"),
            forma_pago=item.get("forma_pago", ""),
            concepto=item["concepto"],
            notas=linea.notas or item.get("notas", ""),
            subtotal=linea.monto,
            impuestos=0,
            sale_de_caja=bool(item.get("sale_de_caja")),
            fecha=fecha,
        )
        try:
            r = _registrar_gasto(gasto)
        except HTTPException as e:
            resultados.append({
                "recurrente_id": linea.recurrente_id, "nombre": item["nombre"],
                "ok": False, "error": str(e.detail),
            })
            continue

        # `persistir=False` + un guardado al final: así N pagos no escriben N
        # veces en Redis.
        recurrentes_store.marcar_pago(linea.recurrente_id, fecha, linea.monto,
                                      data=data, persistir=False)
        resultados.append({
            "recurrente_id": linea.recurrente_id, "nombre": item["nombre"],
            "ok": True, "expense_id": r["expense_id"], "total": r["total"],
        })

    if any(r["ok"] for r in resultados):
        try:
            recurrentes_store.guardar(data)
        except Exception as e:
            # Los gastos SÍ quedaron en Loggro; solo se perdió el "último pago".
            print("[crear_gastos_lote] No se pudo guardar el último pago:", e)

    creados = [r for r in resultados if r["ok"]]
    return {
        "ok": len(creados) == len(resultados),
        "creados": len(creados),
        "fallidos": len(resultados) - len(creados),
        "total": sum(r.get("total", 0) for r in creados),
        "fecha": fecha,
        "detalle": resultados,
    }


# Palabras que acompañan al beneficiario pero no lo identifican. Sin ellas, lo
# que queda de "nomina stalle" o "Pago simon" es el nombre.
_RUIDO_CONCEPTO = {
    "nomina", "pago", "pagos", "pagar", "adelanto", "abono", "completo", "compra",
    "compras", "factura", "efectivo", "transferencia", "recibo", "cuenta",
    "de", "del", "la", "el", "los", "las", "y", "e", "a", "al", "por", "con",
    "para", "se", "le", "que", "es", "en", "sale", "mas", "menos", "dia", "dias",
    "semana", "quincena", "mes", "anterior", "este", "esta", "hoy", "ayer",
    "tipo", "unidades", "unidad", "total",
}

# Un gasto con muchas palabras es una compra surtida ("zanahoria mango limon
# hierbabuena crispetas donas"): repartirle el total a cada palabra daría un
# monto sugerido falso. Un pago a una persona cabe de sobra en tres.
_MAX_PALABRAS_CONCEPTO = 3


@app.get("/api/gastos/recurrentes/sugerencias")
def sugerir_recurrentes(dias: int = Query(180, ge=30, le=730)):
    """Propone beneficiarios recurrentes leyendo el historial de gastos.

    Sirve para sembrar la lista sin escribirla a mano y sin que se olvide
    alguien. Agrupa por la palabra significativa de la descripción porque el
    mismo pago está escrito de varias formas ("Nomina Simon", "Pago simon",
    "simon nomina 09/05" son todos Simón).

    No crea nada: devuelve candidatos para que la vista los ofrezca.
    """
    hoy = dt.date.today()
    desde = hoy - dt.timedelta(days=dias)
    try:
        gastos = cliente().get_expenses(
            f"{desde.isoformat()}T00:00:00.000Z",
            f"{(hoy + dt.timedelta(days=1)).isoformat()}T00:00:00.000Z",
        )
    except Exception as e:
        raise HTTPException(502, f"Error consultando el historial de gastos: {e}")

    def _ref_id(v: Any) -> Optional[str]:
        """El campo puede venir poblado (dict) o como id suelto."""
        if isinstance(v, dict):
            return v.get("_id")
        return v or None

    ya = set(recurrentes_store.cargar()["items"].keys())
    candidatos: dict[str, dict[str, Any]] = {}

    for g in gastos:
        desc = _sin_acentos(g.get("description") or "").lower()
        # Fuera fechas (09/05), montos pegados (400000) y signos.
        desc = re.sub(r"\d+[/-]\d+([/-]\d+)?", " ", desc)
        desc = re.sub(r"[^a-z\s]", " ", desc)
        fecha = (g.get("date") or "")[:10]
        total = (g.get("subTotal") or 0) + (g.get("taxes") or 0)
        tipo = _ref_id(g.get("typeExpense"))

        palabras = [p for p in desc.split()
                    if len(p) >= 4 and p not in _RUIDO_CONCEPTO]
        if not palabras or len(palabras) > _MAX_PALABRAS_CONCEPTO:
            continue

        for palabra in palabras:
            c = candidatos.setdefault(palabra, {
                "veces": 0, "ultimo_pago": "", "montos": [], "tipos": {},
            })
            c["veces"] += 1
            c["montos"].append(int(total))
            if tipo:
                c["tipos"][tipo] = c["tipos"].get(tipo, 0) + 1
            if fecha >= c["ultimo_pago"]:
                c["ultimo_pago"] = fecha

    tipos_nombre = {t["id"]: t["name"] for t in cargar_tipos_gasto()}
    salida = []
    for palabra, c in candidatos.items():
        if c["veces"] < 3:            # 3+ apariciones = se repite de verdad
            continue
        slug = recurrentes_store.slugify(palabra)
        tipo_id = max(c["tipos"], key=c["tipos"].get) if c["tipos"] else None
        # Mediana, no el último ni el promedio: con montos que van de 25.500 a
        # 144.500 el promedio lo estira un pago grande y el último es azar.
        montos = sorted(c["montos"])
        salida.append({
            "id": slug,
            "nombre": palabra.capitalize(),
            "veces": c["veces"],
            "ultimo_pago": c["ultimo_pago"] or None,
            "dias_desde_ultimo": _dias_desde(c["ultimo_pago"]),
            "monto_sugerido": montos[len(montos) // 2],
            "monto_min": montos[0],
            "monto_max": montos[-1],
            "type_expense_id": tipo_id,
            "tipo_nombre": tipos_nombre.get(tipo_id or "", ""),
            "ya_registrado": slug in ya,
        })

    salida.sort(key=lambda s: s["veces"], reverse=True)
    return {"desde": desde.isoformat(), "hasta": hoy.isoformat(), "sugerencias": salida}


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


# --------------------------------------------------------------------------- #
# Utilidad (ventas contra compras + gastos)
# --------------------------------------------------------------------------- #
@app.get("/api/utilidad")
def get_utilidad(desde: Optional[str] = None, hasta: Optional[str] = None,
                 meses: int = Query(6, ge=1, le=36)):
    """Utilidad mes a mes y avisos de registros que podrían faltar.

    La agrupación vive en `informe_utilidad.py`, el mismo módulo que usan la
    consola y el CSV, para que las cifras no se puedan desincronizar.
    """
    fin = dt.date.fromisoformat(hasta) if hasta else dt.date.today()
    if desde:
        ini = dt.date.fromisoformat(desde)
    else:
        m = fin.month - meses
        ini = dt.date(fin.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
    if ini > fin:
        raise HTTPException(400, "La fecha inicial es posterior a la final.")

    try:
        crudos = informe_utilidad.traer(cliente(), ini, fin)
    except Exception as e:
        raise HTTPException(502, f"Error consultando ventas/compras/gastos en Loggro: {e}")
    return informe_utilidad.agrupar(crudos, ini, fin)
