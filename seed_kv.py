"""
seed_kv.py — Sube la homologación local (homologacion.json) a Redis/KV una sola vez.

Uso (con las variables disponibles, p.ej. en el .env o exportadas):
    # Opción A — cadena de conexión (integración Redis de Vercel/Upstash):
    REDIS_URL=rediss://...    python seed_kv.py
    # Opción B — API REST de Upstash/Vercel KV:
    KV_REST_API_URL=...  KV_REST_API_TOKEN=...    python seed_kv.py

Reutiliza homologacion_store.guardar(), así respeta el mismo orden de backends
que usa la app en producción (Redis -> KV REST -> archivo).
"""
import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import homologacion_store as store

if not (store._redis_url() or store._kv_rest_enabled()):
    raise SystemExit(
        "Falta el almacén remoto en el entorno. Define REDIS_URL (o KV_URL) "
        "o KV_REST_API_URL/KV_REST_API_TOKEN (o UPSTASH_REDIS_REST_URL/TOKEN)."
    )

with open("homologacion.json", encoding="utf-8") as f:
    data = json.load(f)

store.guardar(data)
provs = len(data.get("providers", {}))
backend = "Redis (REDIS_URL)" if store._redis_url() else "KV REST"
print(f"OK: homologacion subida a {backend} ({provs} proveedores).")
