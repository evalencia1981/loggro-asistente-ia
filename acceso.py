"""
acceso.py — Puerta de acceso a la API.

Por qué existe: hasta ahora cualquiera con la URL podía leer la cartera
(nombres, cédulas y celulares de los clientes — datos de terceros, no del
negocio) y, peor, crear gastos y movimientos reales en Loggro. No había ninguna
validación antes de los handlers.

Modelo: usuarios con contraseña y un rol (usuarios_store.py), más el código
compartido ACCESO_CODIGO como llave maestra del dueño (sirve para entrar la
primera vez y crear los usuarios, y para no quedar nunca por fuera). Al entrar
se entrega una cookie firmada; la cookie es lo que viaja en cada petición.

Roles: cada uno ve unos módulos (ROLES). El middleware traduce la ruta pedida a
su módulo (RUTAS_MODULO) y rechaza con 403 lo que el rol no tiene. Esconder
pestañas en el frontend es solo comodidad.

Modos previstos:
  * "dueno" -> datos reales, lectura y escritura.
  * "demo"  -> datos ficticios y solo lectura.

CUIDADO con el modo demo: mientras no exista el módulo de datos ficticios, un
visitante en modo demo leería los datos REALES (sin poder escribir, pero
leyéndolos). Por eso ACCESO_CODIGO_DEMO NO debe definirse en producción hasta
que la fase 2 esté desplegada. Sin esa variable el modo demo no se puede abrir
y el botón ni siquiera aparece.

FALLA CERRADO: si no hay ACCESO_CODIGO en el entorno no se abre nada. Un gate de
seguridad que se desactiva solo cuando falta configuración no es un gate.
"""
from __future__ import annotations

import os
import hmac
import json
import time
import base64
import hashlib

COOKIE = "loggro_acceso"
DURACION = 30 * 24 * 3600  # 30 días

MODO_DUENO = "dueno"
MODO_DEMO = "demo"

# --------------------------------------------------------------------------- #
# Roles y módulos
# --------------------------------------------------------------------------- #
MODULOS = ("compras", "inventario", "stock", "gastos", "cartera", "utilidad", "usuarios")

ROLES: dict[str, dict] = {
    "dueno": {"nombre": "Dueño", "modulos": MODULOS,
              "ayuda": "Siempre ve todo, incluida la administración de usuarios."},
    "admin": {"nombre": "Administrador",
              "modulos": ("compras", "inventario", "stock", "gastos", "cartera"),
              "ayuda": "Encargado del negocio. Tú eliges qué módulos ve."},
    "bodega": {"nombre": "Bodega / Barra", "modulos": ("compras", "inventario", "stock"),
               "ayuda": "Personal de barra y bodega. Tú eliges qué módulos ve."},
}
# Los módulos de cada rol (menos el dueño) los puede cambiar el dueño desde la
# pantalla de Usuarios; lo de arriba es el valor por defecto. "usuarios" nunca
# se le puede dar a otro rol: quien maneja usuarios podría hacerse dueño.
ROLES_FIJOS = ("dueno",)
MODULOS_ASIGNABLES = tuple(m for m in MODULOS if m != "usuarios")


def modulos_de_rol(rol: str, usar_cache: bool = True) -> list[str]:
    """Módulos vigentes del rol: los elegidos por el dueño o los de por defecto."""
    if rol in ROLES_FIJOS:
        return list(ROLES[rol]["modulos"])
    import usuarios_store  # import diferido: acceso.py no debe exigir el KV para cargar
    elegidos = usuarios_store.modulos_de_rol(rol, usar_cache=usar_cache)
    base = elegidos if elegidos is not None else ROLES[rol]["modulos"]
    # Orden de MODULOS (así salen las pestañas) y nunca "usuarios".
    return [m for m in MODULOS_ASIGNABLES if m in base]


# El demo enseña todo menos la administración, y en solo lectura.
MODULOS_DEMO = tuple(m for m in MODULOS if m != "usuarios")

# Prefijo de ruta -> módulo. Gana el primero que coincida (lo específico va antes).
# Lo que no está aquí (productos, proveedores, homologación, caché) es común a
# cualquier sesión válida: lo usan varias pantallas.
RUTAS_MODULO: tuple[tuple[str, str], ...] = (
    ("/api/inventario/existencias", "stock"),
    ("/api/inventario", "inventario"),
    ("/api/extraer", "compras"),
    ("/api/chat", "compras"),
    ("/api/movimiento", "compras"),
    ("/api/gastos", "gastos"),
    ("/api/creditos", "cartera"),
    ("/api/utilidad", "utilidad"),
    ("/api/usuarios", "usuarios"),
)


def modulo_de_ruta(path: str) -> str | None:
    for prefijo, modulo in RUTAS_MODULO:
        if path == prefijo or path.startswith(prefijo + "/"):
            return modulo
    return None


# Un código corto se adivina a fuerza bruta. No es una contraseña de usuario:
# es un secreto compartido, así que puede (y debe) ser largo.
LARGO_MINIMO = 10

# Rutas que nunca piden código.
#   * /api/health   -> lo consulta Vercel y el arranque local.
#   * /api/acceso*  -> es la puerta misma.
#   * /api/catalogo -> tiene su propia X-API-Key para las apps externas
#                      (Apptender). Meterle también la cookie la rompería.
ABIERTAS = ("/api/health", "/api/acceso", "/api/catalogo")

# Métodos que modifican datos: en modo demo se rechazan.
ESCRITURA = ("POST", "PUT", "PATCH", "DELETE")


def _codigo(modo: str) -> str:
    """Código configurado para un modo. Vacío = ese modo no está habilitado."""
    if modo == MODO_DEMO:
        return os.getenv("ACCESO_CODIGO_DEMO", "")
    return os.getenv("ACCESO_CODIGO", "")


def _secreto() -> bytes:
    """Clave con la que se firman las cookies.

    Si no se define ACCESO_SECRETO se deriva del propio código. Consecuencia
    buscada: cambiar el código invalida todas las sesiones abiertas.
    """
    s = os.getenv("ACCESO_SECRETO") or _codigo(MODO_DUENO)
    return hashlib.sha256(s.encode()).digest()


def configurado() -> bool:
    return len(_codigo(MODO_DUENO)) >= LARGO_MINIMO


def _firmar(payload: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_secreto(), payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")


def crear_token(modo: str, usuario: str | None = None, sesion: int | None = None) -> str:
    """Token firmado: <payload_b64>.<firma>. No lleva el código ni la clave adentro.

    Con `usuario`, el rol NO va en el token: se lee del almacén en cada petición,
    para que un cambio de rol aplique sin esperar a que venza la cookie.
    """
    datos: dict = {"modo": modo, "exp": int(time.time()) + DURACION}
    if usuario:
        datos.update(u=usuario, s=sesion)
    payload = json.dumps(datos, separators=(",", ":"))
    p64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{p64}.{_firmar(p64)}"


def _datos_de_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    p64, firma = token.rsplit(".", 1)
    # compare_digest: la comparación no debe filtrar en cuánto tarda.
    if not hmac.compare_digest(firma, _firmar(p64)):
        return None
    try:
        datos = json.loads(base64.urlsafe_b64decode(p64 + "=" * (-len(p64) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if datos.get("exp", 0) < time.time():
        return None
    return datos if datos.get("modo") in (MODO_DUENO, MODO_DEMO) else None


def sesion_de_token(token: str | None) -> dict | None:
    """Quién es y qué puede ver, o None si el token es inválido, vencido o revocado.

    -> {modo, usuario, nombre, rol, rol_nombre, modulos}
    """
    datos = _datos_de_token(token)
    if not datos:
        return None
    if datos["modo"] == MODO_DEMO:
        return {"modo": MODO_DEMO, "usuario": None, "nombre": "Demo", "rol": "demo",
                "rol_nombre": "Demo", "modulos": list(MODULOS_DEMO)}
    usuario = datos.get("u")
    if not usuario:  # entró con el código maestro
        return {"modo": MODO_DUENO, "usuario": None, "nombre": "Código maestro",
                "rol": "dueno", "rol_nombre": ROLES["dueno"]["nombre"],
                "modulos": list(MODULOS)}
    import usuarios_store  # import diferido: acceso.py no debe exigir el KV para cargar
    u = usuarios_store.obtener(usuario, usar_cache=True)
    if (u is None or not u.get("activo", True) or u.get("sesion") != datos.get("s")
            or u.get("rol") not in ROLES):
        return None
    return {"modo": MODO_DUENO, "usuario": usuario, "nombre": u.get("nombre") or usuario,
            "rol": u["rol"], "rol_nombre": ROLES[u["rol"]]["nombre"],
            "modulos": modulos_de_rol(u["rol"])}


def verificar_codigo(codigo: str) -> str | None:
    """Modo que abre ese código, o None si no abre nada."""
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    for modo in (MODO_DUENO, MODO_DEMO):
        esperado = _codigo(modo)
        if len(esperado) >= LARGO_MINIMO and hmac.compare_digest(codigo, esperado):
            return modo
    return None


def ruta_abierta(path: str) -> bool:
    return any(path.startswith(p) for p in ABIERTAS)


# --------------------------------------------------------------------------- #
# Freno de fuerza bruta
# --------------------------------------------------------------------------- #
# Se apoya en el Redis que ya usa el proyecto. Si no hay KV vivo NO se bloquea
# el acceso: el freno es una defensa extra, no la puerta. Que se caiga el KV no
# puede dejar al dueño por fuera.
MAX_INTENTOS = 10
VENTANA = 300  # segundos


def _redis():
    from homologacion_store import _redis_url, _redis  # import diferido
    return _redis() if _redis_url() else None


def intento_fallido(ip: str) -> None:
    try:
        r = _redis()
        if r:
            clave = f"acceso:intentos:{ip}"
            r.incr(clave)
            r.expire(clave, VENTANA)
    except Exception:
        pass


def bloqueado(ip: str) -> bool:
    try:
        r = _redis()
        if not r:
            return False
        return int(r.get(f"acceso:intentos:{ip}") or 0) >= MAX_INTENTOS
    except Exception:
        return False


def limpiar_intentos(ip: str) -> None:
    try:
        r = _redis()
        if r:
            r.delete(f"acceso:intentos:{ip}")
    except Exception:
        pass
