"""Cliente mínimo para la Google Analytics Data API (GA4).

Llama directamente al endpoint REST `runReport` con una cuenta de servicio.
No usa la librería oficial `google-analytics-data`: para dos llamadas no
compensa arrastrar sus dependencias, y así la estructura de la petición
queda a la vista.

Autenticación: una cuenta de servicio de Google Cloud con el rol "Lector"
añadida en la propiedad de GA4 (Administrar > Gestión de accesos).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
ENDPOINT = "https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport"


class GA4Error(RuntimeError):
    """Error devuelto por la API o de configuración."""


@dataclass
class Informe:
    """Respuesta de runReport ya aplanada en filas de dict."""

    dimensiones: list[str]
    metricas: list[str]
    filas: list[dict[str, Any]] = field(default_factory=list)
    total_filas: int = 0

    def columna(self, nombre: str) -> list[Any]:
        return [f[nombre] for f in self.filas]


class ClienteGA4:
    def __init__(self, property_id: str, credenciales: str | Path | dict | None = None, timeout: int = 60):
        self.property_id = str(property_id).replace("properties/", "")
        self.timeout = timeout
        self._creds = self._cargar_credenciales(credenciales)
        self._session = requests.Session()

    # --- autenticación -------------------------------------------------------

    @staticmethod
    def _cargar_credenciales(fuente):
        """Acepta ruta a JSON, dict ya cargado, o la variable GOOGLE_APPLICATION_CREDENTIALS."""
        if fuente is None:
            fuente = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if not fuente:
                raise GA4Error(
                    "Sin credenciales. Pasa la ruta del JSON de la cuenta de servicio "
                    "o define GOOGLE_APPLICATION_CREDENTIALS."
                )
        if isinstance(fuente, dict):
            return service_account.Credentials.from_service_account_info(fuente, scopes=SCOPES)
        ruta = Path(fuente)
        if not ruta.exists():
            raise GA4Error(f"No existe el archivo de credenciales: {ruta}")
        return service_account.Credentials.from_service_account_file(str(ruta), scopes=SCOPES)

    def _token(self) -> str:
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token

    # --- llamada -------------------------------------------------------------

    def run_report(self, cuerpo: dict) -> Informe:
        url = ENDPOINT.format(property_id=self.property_id)
        resp = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
            data=json.dumps(cuerpo),
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                msg = resp.text
            raise GA4Error(f"GA4 API {resp.status_code}: {msg}")
        return aplanar_respuesta(resp.json())


def aplanar_respuesta(datos: dict) -> Informe:
    """Convierte la respuesta de runReport en filas de dict.

    La API devuelve cabeceras y valores por separado y todo como string;
    aquí emparejamos cada valor con su nombre y convertimos las métricas
    a número, que es lo que quiere cualquier código que venga después.
    """
    dims = [d["name"] for d in datos.get("dimensionHeaders", [])]
    mets = [m["name"] for m in datos.get("metricHeaders", [])]
    tipos = {m["name"]: m.get("type", "TYPE_INTEGER") for m in datos.get("metricHeaders", [])}

    filas = []
    for fila in datos.get("rows", []):
        registro: dict[str, Any] = {}
        for nombre, celda in zip(dims, fila.get("dimensionValues", [])):
            registro[nombre] = celda.get("value", "")
        for nombre, celda in zip(mets, fila.get("metricValues", [])):
            bruto = celda.get("value", "0")
            registro[nombre] = _a_numero(bruto, tipos.get(nombre, ""))
        filas.append(registro)

    return Informe(dimensiones=dims, metricas=mets, filas=filas, total_filas=datos.get("rowCount", len(filas)))


def _a_numero(valor: str, tipo: str):
    try:
        if tipo in ("TYPE_INTEGER",):
            return int(valor)
        return float(valor)
    except (TypeError, ValueError):
        return 0
