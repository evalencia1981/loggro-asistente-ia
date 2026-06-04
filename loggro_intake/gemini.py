"""
loggro_intake.gemini — Cliente mínimo de Google Gemini (structured outputs vía REST).

Helper compartido por el extractor de imágenes y el chat. Usa el free tier de Gemini;
requiere GEMINI_API_KEY en el entorno. Modelo por defecto: gemini-2.5-flash
(gemini-2.0-flash tiene el free tier en 0 en algunas cuentas). Reintenta ante
503/429/5xx ("high demand"), que Gemini devuelve de forma intermitente.
"""
from __future__ import annotations

import os
import json
import time

import requests

DEFAULT_MODEL = "gemini-2.5-flash"
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def model_name() -> str:
    return os.getenv("LOGGRO_EXTRACTOR_MODEL", DEFAULT_MODEL)


def generar_json(parts: list[dict], schema: dict, model: str | None = None,
                 max_tokens: int = 8192) -> dict:
    """Llama a Gemini con `parts` (texto y/o imágenes) y un responseSchema.

    Devuelve el dict ya parseado que cumple `schema`. Reintenta ante saturación.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno (.env).")

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "maxOutputTokens": max_tokens,
            # gemini-2.5-flash usa "thinking" por defecto y consume el presupuesto de
            # salida -> en facturas largas truncaba el JSON. Lo desactivamos para que
            # todos los tokens vayan al JSON estructurado.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = _URL.format(model=model or model_name())

    resp = None
    for intento in range(4):
        resp = requests.post(url, params={"key": api_key}, json=body, timeout=120)
        if resp.ok:
            break
        if resp.status_code in (429, 500, 502, 503, 504) and intento < 3:
            time.sleep(2 * (intento + 1))  # 2s, 4s, 6s
            continue
        raise RuntimeError(f"Gemini {resp.status_code}: {resp.text[:300]}")
    if resp is None or not resp.ok:
        raise RuntimeError(
            f"Gemini sigue saturado tras varios reintentos: {getattr(resp, 'status_code', '?')}"
        )

    data = resp.json()
    cand = (data.get("candidates") or [{}])[0]
    try:
        text = cand["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Respuesta inesperada de Gemini: {json.dumps(data)[:300]}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Causa típica: el documento es muy largo y se acabó el presupuesto de tokens.
        if cand.get("finishReason") == "MAX_TOKENS":
            raise RuntimeError(
                "El documento es muy largo y la respuesta se truncó. "
                "Intenta de nuevo o reduce el detalle."
            ) from e
        raise RuntimeError(f"Gemini devolvió un JSON inválido: {e}") from e
