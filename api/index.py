"""
api/index.py — Punto de entrada para las funciones serverless de Vercel.

Expone la app FastAPI (backend/app.py) como ASGI. Vercel enruta /api/* aquí
(ver vercel.json). En local seguimos usando uvicorn backend.app:app directamente.
"""
import os
import sys

# La raíz del repo (un nivel arriba de /api) para importar backend/, loggro_intake/, etc.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import app  # noqa: E402,F401  (Vercel sirve este `app` ASGI)
