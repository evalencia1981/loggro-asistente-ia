"""
test_lectura.py — Prueba de SOLO LECTURA contra Loggro Restobar.
No modifica nada en tu inventario. Sirve para:
  1) Confirmar que el login funciona y la API responde con tu cuenta.
  2) Ver el id del tipo "Entrada - Compra".
  3) Listar tus productos y obtener el _id de cada uno (para la homologación).

USO:
  1) pip install requests python-dotenv
  2) Crea un archivo .env junto a este script con:
        LOGGRO_BASE_URL=https://api.pirpos.com
        LOGGRO_EMAIL=tu_correo
        LOGGRO_PASSWORD=tu_clave
  3) python3 test_lectura.py

Si el login falla, revisa los nombres de los campos del body en
developer.loggro.com (endpoint /login). Aquí se prueban variantes comunes.
"""

import os
import json
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # si no está python-dotenv, usa variables de entorno del sistema

BASE = os.getenv("LOGGRO_BASE_URL", "https://api.pirpos.com").rstrip("/")
EMAIL = os.getenv("LOGGRO_EMAIL")
PASSWORD = os.getenv("LOGGRO_PASSWORD")


def login() -> str:
    if not EMAIL or not PASSWORD:
        raise SystemExit("Falta LOGGRO_EMAIL / LOGGRO_PASSWORD en el .env")

    # Se prueban variantes de nombres de campo por si la doc difiere.
    intentos = [
        {"email": EMAIL, "password": PASSWORD},
        {"username": EMAIL, "password": PASSWORD},
        {"user": EMAIL, "password": PASSWORD},
    ]
    last = None
    for body in intentos:
        r = requests.post(f"{BASE}/login", json=body, timeout=30)
        last = r
        if r.ok:
            data = r.json()
            token = data.get("tokenCurrent") or data.get("token")
            if token:
                print(f"✓ Login OK (campos: {list(body.keys())})")
                return token
    raise SystemExit(f"✗ Login falló. Último status={last.status_code}, body={last.text[:300]}")


def main():
    print(f"Base URL: {BASE}")
    token = login()
    h = {"Authorization": f"Bearer {token}"}

    # 1) Tipos de inventario
    r = requests.get(f"{BASE}/inventories/types/all", headers=h, timeout=30)
    r.raise_for_status()
    tipos = r.json()
    print("\n== Tipos de inventario ==")
    for t in tipos:
        marca = "  <-- USAR ESTE" if (t.get("name", "").strip().lower() == "entrada - compra") else ""
        print(f"  id={t.get('id')}  name={t.get('name')}{marca}")

    # 2) Productos (primeros 20 para no saturar)
    r = requests.get(f"{BASE}/products", headers=h,
                     params={"pagination": "true", "limit": 20, "page": 0}, timeout=30)
    r.raise_for_status()
    data = r.json()
    productos = data.get("data", data) if isinstance(data, dict) else data
    print(f"\n== Productos (mostrando {min(20, len(productos))}) ==")
    for p in productos[:20]:
        print(f"  _id={p.get('_id')}  name={p.get('name')}")

    # 3) Volcar todo a un archivo para construir la homologación
    with open("productos_loggro.json", "w", encoding="utf-8") as f:
        json.dump([{"_id": p.get("_id"), "name": p.get("name")} for p in productos],
                  f, indent=2, ensure_ascii=False)
    print("\n✓ Guardado productos_loggro.json (úsalo para armar homologacion.json)")
    print("✓ Prueba de lectura completa. No se modificó nada.")


if __name__ == "__main__":
    main()
