"""
loggro_client.py
Cliente para automatizar el registro de compras (Entrada - Compra) en Loggro Restobar
vía API nativa (https://api.pirpos.com).

Flujo: login -> resolver tipo "Entrada - Compra" -> homologar productos/proveedor
       -> construir movimiento -> (aprobación humana) -> POST -> conciliar.

Requisitos: pip install requests python-dotenv
Variables de entorno (.env, NO subir al repo):
    LOGGRO_BASE_URL=https://api.pirpos.com
    LOGGRO_EMAIL=tu_correo
    LOGGRO_PASSWORD=tu_clave

NOTA: 3 rutas están marcadas como POR CONFIRMAR contra developer.loggro.com
      (proveedores, pagos y el método/ruta del create). El resto está verificado
      contra la documentación OpenAPI de Restobar.
"""

from __future__ import annotations

import os
import sys
import json
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # si no está python-dotenv, usa variables de entorno del sistema

# Consola de Windows: forzar UTF-8 para imprimir ✓/acentos sin UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

COST_BASIS = "con_impuestos"  # "con_impuestos" | "sin_iva"
TIPO_COMPRA_NOMBRE = "Entrada - Compra"

# Ubicación/bodega destino del stock. La cuenta Virus Pub tiene una sola: "General".
# Se puede sobreescribir con la variable de entorno LOGGRO_LOCATION_STOCK.
LOCATION_STOCK_ID = os.getenv("LOGGRO_LOCATION_STOCK", "67c398d9be2bbaa69edebdf3")


# --------------------------------------------------------------------------- #
# Cliente HTTP
# --------------------------------------------------------------------------- #
class LoggroClient:
    def __init__(self, base_url: str | None = None,
                 email: str | None = None, password: str | None = None,
                 timeout: int = 30):
        self.base_url = (base_url or os.getenv("LOGGRO_BASE_URL", "https://api.pirpos.com")).rstrip("/")
        self.email = email or os.getenv("LOGGRO_EMAIL")
        self.password = password or os.getenv("LOGGRO_PASSWORD")
        self.timeout = timeout
        self.token: str | None = None
        self.s = requests.Session()

    # -- auth ----------------------------------------------------------------
    def login(self, retries: int = 3) -> str:
        """POST /login -> tokenCurrent (JWT). Campos confirmados: email + password.

        El servidor de PirPos devuelve 500 de forma intermitente; se reintenta.
        Un 400 ('Correo o contraseña incorrectos.') NO se reintenta: son credenciales.
        """
        last = None
        for intento in range(1, retries + 1):
            r = self.s.post(f"{self.base_url}/login",
                            json={"email": self.email, "password": self.password},
                            timeout=self.timeout)
            last = r
            if r.ok:
                data = r.json()
                self.token = data.get("tokenCurrent") or data.get("token")
                if not self.token:
                    raise RuntimeError(f"No se obtuvo token del login: {data}")
                self.s.headers.update({"Authorization": f"Bearer {self.token}"})
                return self.token
            if r.status_code >= 500 and intento < retries:
                continue  # fallo transitorio del servidor -> reintentar
            break
        last.raise_for_status()  # 4xx (p.ej. credenciales) -> lanza con el mensaje real

    def _get(self, path: str, **params) -> Any:
        r = self.s.get(f"{self.base_url}{path}",
                       params={k: v for k, v in params.items() if v is not None},
                       timeout=self.timeout)
        if r.status_code == 401:        # token expirado -> re-login y reintento
            self.login()
            r = self.s.get(f"{self.base_url}{path}",
                           params={k: v for k, v in params.items() if v is not None},
                           timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: Any) -> Any:
        r = self.s.post(f"{self.base_url}{path}", json=body, timeout=self.timeout)
        if r.status_code == 401:
            self.login()
            r = self.s.post(f"{self.base_url}{path}", json=body, timeout=self.timeout)
        if not r.ok:
            # Surface el mensaje real de Loggro (no solo "500 Server Error").
            raise RuntimeError(f"{r.status_code} en {path}: {r.text[:500]}")
        return r.json()

    def _delete(self, path: str) -> Any:
        r = self.s.delete(f"{self.base_url}{path}", timeout=self.timeout)
        if r.status_code == 401:
            self.login()
            r = self.s.delete(f"{self.base_url}{path}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # -- catálogos -----------------------------------------------------------
    def get_inventory_types(self) -> list[dict]:
        """GET /inventories/types/all -> [{id, name, isSubtracted, isProduction, isMoveTo}]"""
        return self._get("/inventories/types/all")

    def get_tipo_compra_id(self) -> int:
        for t in self.get_inventory_types():
            if (t.get("name") or "").strip().lower() == TIPO_COMPRA_NOMBRE.lower():
                return int(t["id"])
        raise RuntimeError(f"No se encontró el tipo '{TIPO_COMPRA_NOMBRE}'")

    def get_products(self, name: str | None = None) -> list[dict]:
        """GET /products -> productos con _id y name."""
        data = self._get("/products", name=name, pagination=False)
        return data.get("data", data) if isinstance(data, dict) else data

    def get_providers(self) -> list[dict]:
        """GET /providers  (RUTA POR CONFIRMAR)."""
        data = self._get("/providers", pagination=False)
        return data.get("data", data) if isinstance(data, dict) else data

    # -- escritura -----------------------------------------------------------
    def create_movement(self, payload: dict) -> dict:
        """POST /inventories -> crea el movimiento (con '_id' en el body = edición).

        Devuelve el objeto creado con su '_id'. Afecta stock y avgCost por ubicación.
        """
        return self._post("/inventories", payload)

    def delete_movement(self, movement_id: str) -> dict:
        """DELETE /inventories/{_id} -> revierte el movimiento (stock y avgCost)."""
        return self._delete(f"/inventories/{movement_id}")

    def get_movements(self, provider: str | None = None, inventory_type_id: int | None = None,
                      inventory_number: str | None = None, purchase_status: bool | None = None) -> list[dict]:
        """GET /inventories con filtros -> conciliación / pendientes por pagar."""
        data = self._get("/inventories", provider=provider, inventoryTypeId=inventory_type_id,
                         inventoryNumber=inventory_number, purchaseStatus=purchase_status)
        return data.get("data", data) if isinstance(data, dict) else data

    def register_payment(self, payload: dict) -> dict:
        """POST /inventories/payments  (RUTA POR CONFIRMAR: guardarpagoinventario)."""
        return self._post("/inventories/payments", payload)


# --------------------------------------------------------------------------- #
# Homologación
# --------------------------------------------------------------------------- #
def cargar_homologacion(path: str = "homologacion.json") -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def resolver_item_id(descripcion: str, homolog: dict[str, str]) -> str | None:
    return homolog.get(descripcion.strip().upper())


# --------------------------------------------------------------------------- #
# Construcción del payload
# --------------------------------------------------------------------------- #
def costo_unitario(item: dict) -> float:
    cant = item["cantidad"] or 1
    if COST_BASIS == "sin_iva":
        return round(item["base"] / cant)
    return round(item["total"] / cant)  # con_impuestos


def construir_movimiento(extraccion: dict, homolog: dict[str, str],
                         type_id: int, provider_id: str) -> dict:
    # 1) Validación de cuadre (control duro)
    suma = sum(i["total"] for i in extraccion["items"])
    if suma != extraccion["totales"]["total_pagar"]:
        raise ValueError(f"La factura no cuadra: líneas={suma} vs total={extraccion['totales']['total_pagar']}")

    # 2) Homologación de cada línea
    detalles, sin_homologar = [], []
    for it in extraccion["items"]:
        item_id = resolver_item_id(it["descripcion"], homolog)
        if not item_id:
            sin_homologar.append(it["descripcion"])
            continue
        detalles.append({"ingredient": item_id,
                         "quantity": it["cantidad"],
                         "price": costo_unitario(it),
                         "locationStock": LOCATION_STOCK_ID,
                         "note": ""})
    if sin_homologar:
        raise ValueError(f"Ítems sin homologar (mapear en homologacion.json): {sin_homologar}")

    pagado = bool(extraccion["documento"].get("pagado", False))
    total = extraccion["totales"]["total_pagar"]
    fecha = extraccion["documento"].get("fecha") or dt.date.today().isoformat()

    # Esquema alineado con movimientos reales leídos de /inventories (type=1):
    #   - 'total' a nivel raíz (= invoice.total)
    #   - invoice solo con invoiceNumber/isPaid/total (totalPaid y subtractCashRegister
    #     pertenecen al flujo de pago: POST /inventories/payments)
    #   - cada línea con locationStock + note
    return {
        "date": f"{fecha}T00:00:00.000Z",
        "type": type_id,
        "provider": provider_id,
        "note": f"Compra {extraccion['proveedor'].get('nombre_tirilla', '')}".strip(),
        "total": total,
        "invoice": {
            "invoiceNumber": extraccion["documento"].get("numero", ""),
            "isPaid": pagado,
            "total": total,
        },
        "ingredients": detalles,
    }


def conciliar(cli: LoggroClient, invoice_number: str, total_esperado: int) -> bool:
    movs = cli.get_movements(inventory_number=invoice_number)
    for m in movs:
        if (m.get("invoice") or {}).get("total") == total_esperado:
            return True
    return False


# --------------------------------------------------------------------------- #
# Datos de prueba (tirilla "Donde el Calvo")
# --------------------------------------------------------------------------- #
EXTRACCION_PRUEBA = {
    "proveedor": {"nombre_tirilla": "ESTANQUILLO Y CIGARRERIA DONDE EL CALVO", "nit": "1039473492"},
    "documento": {"numero": "DEC0001", "tipo": "PRECUENTA_COPIA", "forma_pago": "CONTADO",
                  "pagado": False, "fecha": "2026-06-01"},
    "items": [
        {"cod_proveedor": "000474", "descripcion": "POKER 330ML",        "um": "WSD", "cantidad": 60, "total": 137400, "base": 94165, "iva_pct": 19, "iva": 17891, "ic_licores": 25344},
        {"cod_proveedor": "000418", "descripcion": "AGUILA 330ML",       "um": "WSD", "cantidad": 60, "total": 142560, "base": 98259, "iva_pct": 19, "iva": 18669, "ic_licores": 25632},
        {"cod_proveedor": "000047", "descripcion": "RON BACARDI CART",   "um": "WSD", "cantidad": 1,  "total": 52788,  "base": 31374, "iva_pct": 5,  "iva": 1569,  "ic_licores": 19845},
        {"cod_proveedor": "000809", "descripcion": "STELLA ARTOIS 6PACK","um": "WSD", "cantidad": 1,  "total": 22977,  "base": 17614, "iva_pct": 19, "iva": 3347,  "ic_licores": 2016},
        {"cod_proveedor": "000460", "descripcion": "HEINEKEN 330ML",     "um": "WSD", "cantidad": 2,  "total": 7938,   "base": 6185,  "iva_pct": 19, "iva": 1175,  "ic_licores": 578},
    ],
    "totales": {"base": 247597, "iva": 42651, "ic_licores": 73415, "total_pagar": 363663},
    "cuadra": True,
}


# --------------------------------------------------------------------------- #
# Ejecución: DRY-RUN por defecto (no escribe). Pasar --post para cargar.
# --------------------------------------------------------------------------- #
def main(dry_run: bool = True):
    homolog = cargar_homologacion()
    # Si aún no hay homologación, se usa un mapa de ejemplo para ver el payload:
    if not homolog:
        homolog = {
            "POKER 330ML": "<id_poker>", "AGUILA 330ML": "<id_aguila>",
            "RON BACARDI CART": "<id_bacardi>", "STELLA ARTOIS 6PACK": "<id_stella>",
            "HEINEKEN 330ML": "<id_heineken>",
        }

    if dry_run:
        payload = construir_movimiento(EXTRACCION_PRUEBA, homolog, type_id=1, provider_id="<id_proveedor>")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    cli = LoggroClient()
    cli.login()
    type_id = cli.get_tipo_compra_id()
    # resolver_provider(...) -> buscar/crear por NIT y obtener su _id
    provider_id = "<id_proveedor>"  # TODO: resolver con get_providers()/crear
    payload = construir_movimiento(EXTRACCION_PRUEBA, homolog, type_id, provider_id)
    print("Payload a enviar:\n", json.dumps(payload, indent=2, ensure_ascii=False))
    # input("Aprobar y enviar? [enter para continuar]")   # humano en el bucle (v1)
    resp = cli.create_movement(payload)
    print("Respuesta:", resp)
    ok = conciliar(cli, payload["invoice"]["invoiceNumber"], payload["invoice"]["total"])
    print("Conciliación:", "OK" if ok else "REVISAR")


if __name__ == "__main__":
    import sys
    main(dry_run="--post" not in sys.argv)
