"""Prueba end-to-end de la API de catálogo contra Loggro real (cuenta Virus pub).

Usa un almacén de catálogo LOCAL (archivo temporal) para no tocar el Redis de prod.
Al final limpia: borra de Loggro los productos que creó.
"""
import os, sys, json, tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

os.environ["CATALOGO_API_KEYS"] = "apptender:clave_de_prueba"
# Forzar almacén en archivo temporal: sin REDIS_URL/KV, catalogo_store usa archivo.
os.environ.pop("REDIS_URL", None); os.environ.pop("KV_URL", None)
os.environ.pop("KV_REST_API_URL", None); os.environ.pop("KV_REST_API_TOKEN", None)
os.environ.pop("UPSTASH_REDIS_REST_URL", None); os.environ.pop("UPSTASH_REDIS_REST_TOKEN", None)

from dotenv import load_dotenv
load_dotenv(os.path.join(RAIZ, ".env"), override=False)
# ...y volver a limpiar por si el .env traía REDIS_URL
for k in ("REDIS_URL", "KV_URL", "KV_REST_API_URL", "KV_REST_API_TOKEN"):
    os.environ.pop(k, None)

import catalogo_store
catalogo_store.CATALOGO_PATH = os.path.join(tempfile.gettempdir(), "catalogo_test.json")
if os.path.exists(catalogo_store.CATALOGO_PATH):
    os.remove(catalogo_store.CATALOGO_PATH)

from fastapi.testclient import TestClient
from backend.app import app
import loggro_session

c = TestClient(app)
H = {"X-API-Key": "clave_de_prueba"}
fallos = []


def paso(titulo, resp, esperado=200, ver=None):
    ok = resp.status_code == esperado
    print(f"\n=== {titulo}  [{resp.status_code}]{'' if ok else '  <-- ESPERABA ' + str(esperado)}")
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    print(json.dumps(body, ensure_ascii=False)[:900] if not isinstance(body, str) else body[:400])
    if not ok:
        fallos.append(titulo)
    elif ver:
        try:
            detalle = ver(body)
            if detalle is not True:
                fallos.append(f"{titulo}: {detalle}")
                print("   !! ", detalle)
        except Exception as ex:
            fallos.append(f"{titulo}: excepcion en verificacion {ex}")
    return body


# 1. auth
paso("sin clave -> 401", c.get("/api/catalogo/health"), 401)
paso("clave mala -> 401", c.get("/api/catalogo/health", headers={"X-API-Key": "no"}), 401)
paso("health", c.get("/api/catalogo/health", headers=H), 200,
     lambda b: True if b["app"] == "apptender" else "app incorrecta")

# 2. catálogo de Loggro
paso("categorias", c.get("/api/catalogo/loggro/categorias", headers=H), 200,
     lambda b: True if len(b) > 0 else "sin categorias")
prods = paso("productos loggro (q=aguila)",
             c.get("/api/catalogo/loggro/productos?q=aguila&limit=5", headers=H), 200)

# 3. homologar: uno que existe en Loggro y uno inventado
nombre_existente = prods[0]["nombre"] if prods else "aguila"
pid_existente = prods[0]["product_id"] if prods else None
hom = paso("homologar (1 parecido + 1 nuevo)", c.post("/api/catalogo/homologar", headers=H, json={
    "items": [{"codigo": "APT-EXIST", "nombre": nombre_existente},
              {"codigo": "APT-NUEVO", "nombre": "ZZ TEST Coctel Inventado XYZ"}]}), 200,
    lambda b: True if b["items"][0]["estado"] == "sugerido" and b["items"][1]["estado"] == "nuevo"
    else f"estados inesperados: {[i['estado'] for i in b['items']]}")

# 4. vincular el existente
paso("vincular APT-EXIST", c.post("/api/catalogo/vinculos", headers=H, json={
    "app_name": "Apptender",
    "vinculos": [{"codigo": "APT-EXIST", "product_id": pid_existente, "nombre_origen": nombre_existente}]}),
    200, lambda b: True if b["ok"] else "no vinculo")

paso("vincular product_id inexistente -> ok:false",
     c.post("/api/catalogo/vinculos", headers=H, json={
         "vinculos": [{"codigo": "APT-X", "product_id": "000000000000000000000000"}]}), 200,
     lambda b: True if not b["ok"] else "deberia fallar")

paso("homologar de nuevo -> ya vinculado", c.post("/api/catalogo/homologar", headers=H, json={
    "items": [{"codigo": "APT-EXIST", "nombre": nombre_existente}]}), 200,
    lambda b: True if b["items"][0]["estado"] == "vinculado" else "no quedo vinculado")

# 5. upsert: crea el nuevo y actualiza el vinculado
precio_orig = prods[0]["precio"] if prods else 0
up = paso("upsert (crear + actualizar precio)", c.post("/api/catalogo/productos", headers=H, json={
    "productos": [
        {"codigo": "APT-NUEVO", "nombre": "ZZ TEST Coctel Inventado XYZ", "precio": 18000,
         "categoria": "Licores", "descripcion": "creado por la API de prueba"},
        {"codigo": "APT-EXIST", "precio": 99999},
    ]}), 200)
creado_id = next((r.get("product_id") for r in up["resultados"] if r["codigo"] == "APT-NUEVO"), None)
print("   acciones:", {r["codigo"]: r["accion"] for r in up["resultados"]})
if up["resumen"].get("creado") != 1 or up["resumen"].get("actualizado") != 1:
    fallos.append(f"upsert resumen inesperado: {up['resumen']}")

# 6. idempotencia
paso("upsert repetido -> sin_cambios", c.post("/api/catalogo/productos", headers=H, json={
    "productos": [{"codigo": "APT-NUEVO", "nombre": "ZZ TEST Coctel Inventado XYZ", "precio": 18000},
                  {"codigo": "APT-EXIST", "precio": 99999}]}), 200,
    lambda b: True if b["resumen"].get("sin_cambios") == 2 else f"no fue idempotente: {b['resumen']}")

# 7. verificar en Loggro que el precio quedó
p = loggro_session.cliente().get_product(creado_id)
print("\n=== verificacion directa en Loggro del creado:",
      {"name": p["name"], "price": p["price"],
       "locPrice": [l.get("price") for l in p.get("locationsStock", [])],
       "cat": (p.get("category") or {}).get("name"), "isActive": p.get("isActive")})
if p["price"] != 18000 or p["locationsStock"][0]["price"] != 18000:
    fallos.append("el precio no quedo escrito en Loggro")

# 8. patch: nombre + desactivar
paso("patch nombre", c.patch("/api/catalogo/productos/APT-NUEVO", headers=H,
                             json={"nombre": "ZZ TEST Coctel Renombrado"}), 200,
     lambda b: True if b["producto"]["nombre"] == "ZZ TEST Coctel Renombrado" else "no renombro")
paso("patch codigo inexistente -> 404",
     c.patch("/api/catalogo/productos/NO-EXISTE", headers=H, json={"precio": 1}), 404)

# 9. desactivar (DELETE sin borrar)
paso("desactivar", c.delete("/api/catalogo/productos/APT-NUEVO", headers=H), 200,
     lambda b: True if b["producto"]["activo"] is False else "sigue activo")

# 10. cambios (flujo inverso): tras nuestros push, todo deberia ser eco -> vacio
paso("cambios (sin eco)", c.get("/api/catalogo/cambios", headers=H), 200,
     lambda b: True if b["total"] == 0 else f"deberia estar vacio, hay {b['total']}: "
     f"{[(x['codigo'], x.get('campos_distintos')) for x in b['cambios']]}")
paso("cambios (incluir_eco=true)", c.get("/api/catalogo/cambios?incluir_eco=true", headers=H), 200,
     lambda b: True if b["total"] == 2 else f"esperaba 2, hay {b['total']}")

# simular cambio hecho desde el POS: tocar el precio directo en Loggro
full = loggro_session.cliente().get_product(creado_id)
full["price"] = 12345
for l in full["locationsStock"]:
    l["price"] = 12345
loggro_session.cliente().update_product(full)
paso("cambios tras editar en el POS -> detecta 1", c.get("/api/catalogo/cambios", headers=H), 200,
     lambda b: True if b["total"] == 1 and b["cambios"][0]["codigo"] == "APT-NUEVO"
     and "precio" in b["cambios"][0]["campos_distintos"] else f"no detecto: {b['cambios']}")

# 11. restaurar el precio del producto REAL que tocamos y limpiar el de prueba
paso("restaurar precio original de APT-EXIST",
     c.patch("/api/catalogo/productos/APT-EXIST", headers=H, json={"precio": precio_orig}), 200,
     lambda b: True if b["producto"]["precio"] == precio_orig else "no restauro")
paso("borrar de Loggro el producto de prueba",
     c.delete("/api/catalogo/productos/APT-NUEVO?borrar=true", headers=H), 200,
     lambda b: True if b["accion"] == "eliminado" else "no borro")
paso("desvincular APT-EXIST", c.delete("/api/catalogo/vinculos/APT-EXIST", headers=H), 200)

print("\n" + "=" * 60)
print("FALLOS:", fallos if fallos else "ninguno")
print("=" * 60)
