"""
seed_kv.py — Sube la homologación local (homologacion.json) a Vercel KV una sola vez.

Uso (con las variables de KV disponibles, p.ej. en el .env):
    KV_REST_API_URL=...    KV_REST_API_TOKEN=...
    python seed_kv.py

Las variables KV_REST_API_URL / KV_REST_API_TOKEN las genera Vercel al crear el KV.
"""
import os
import json

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

url = (os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
token = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
if not url or not token:
    raise SystemExit(
        "Falta el KV en el entorno. Define KV_REST_API_URL/KV_REST_API_TOKEN "
        "o UPSTASH_REDIS_REST_URL/UPSTASH_REDIS_REST_TOKEN."
    )

with open("homologacion.json", encoding="utf-8") as f:
    data = json.load(f)

r = requests.post(
    url,
    headers={"Authorization": f"Bearer {token}"},
    json=["SET", "homologacion", json.dumps(data, ensure_ascii=False)],
    timeout=20,
)
r.raise_for_status()
provs = len(data.get("providers", {}))
print(f"OK: homologación subida a KV ({provs} proveedores). Respuesta: {r.json()}")
