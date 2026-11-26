"""Fixtures comunes.

Dos modos con las mismas pruebas:
- Por defecto: la app corre en proceso (TestClient) con un repositorio en memoria.
- Con VOLTRIX_BASE_URL=http://localhost:8080: las pruebas golpean un servicio real
  (docker compose o EC2) y validan sus respuestas contra openapi.yaml.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient
from openapi_core import OpenAPI
from openapi_core.testing import MockRequest, MockResponse

from app.config import Config
from app.main import create_app
from app.repositorio import BaseDatosNoDisponible, DatosEstado, FiltrosEstado

RAIZ = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("VOLTRIX_BASE_URL", "").rstrip("/")
SERVIDOR_CONTRATO = "http://localhost:8080"  # servidor por defecto declarado en openapi.yaml

solo_en_proceso = pytest.mark.skipif(bool(BASE_URL), reason="requiere controlar la base de datos (modo en proceso)")


def _t(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(timezone.utc)


# Mismos datos que app/migraciones/002_semilla.sql.
SEMILLA = [
    ("ALR-20261125-001", "PL-002", "PL-002-BB-01", "banco_baterias", "temperatura", 46.3, 45, "critica", "activa", 3, "2026-11-25T13:05:00Z", "2026-11-25T13:05:20Z"),
    ("ALR-20261125-002", "PL-001", "PL-001-PS-07", "panel_solar", "caida_potencia", 27.5, 20, "advertencia", "activa", 3, "2026-11-25T13:05:10Z", "2026-11-25T13:06:10Z"),
    ("ALR-20261125-003", "PL-041", "PL-041-TB-03", "turbina", "velocidad_viento", 27.1, 25, "critica", "activa", 5, "2026-11-25T13:00:00Z", "2026-11-25T13:05:00Z"),
    ("ALR-20261125-004", "PL-041", "PL-041-TB-03", "turbina", "velocidad_viento", 22.4, 20, "advertencia", "activa", 3, "2026-11-25T12:40:00Z", "2026-11-25T12:55:00Z"),
    ("ALR-20261124-001", "PL-002", "PL-002-BB-01", "banco_baterias", "temperatura", 41.8, 40, "advertencia", "resuelta", 4, "2026-11-24T09:10:00Z", "2026-11-24T09:40:00Z"),
    ("ALR-20261124-002", "PL-001", "PL-001-PS-07", "panel_solar", "caida_potencia", 43.0, 40, "critica", "resuelta", 3, "2026-11-24T16:00:00Z", "2026-11-24T16:20:00Z"),
]
COLUMNAS = ("id", "planta_id", "activo_id", "tipo_activo", "metrica", "valor_observado", "umbral_aplicado",
            "severidad", "estado", "ocurrencias", "primera_deteccion", "ultima_deteccion")


class RepositorioFalso:
    """Implementa RepositorioAlertas en memoria con la misma semántica de filtros."""

    def __init__(self, retardo: float = 0.0) -> None:
        self.caido = False
        self.retardo = retardo
        self.filas = [dict(zip(COLUMNAS, f)) | {"primera_deteccion": _t(f[10]), "ultima_deteccion": _t(f[11])}
                      for f in SEMILLA]

    def abrir(self) -> None: ...
    def cerrar(self) -> None: ...

    def ping(self) -> None:
        if self.caido:
            raise BaseDatosNoDisponible("conexión rechazada")

    def consultar_estado(self, filtros: FiltrosEstado) -> DatosEstado:
        self.ping()
        if self.retardo:
            time.sleep(self.retardo)
        base = [f for f in self.filas
                if (not filtros.planta_id or f["planta_id"] == filtros.planta_id)
                and (not filtros.activo_id or f["activo_id"] == filtros.activo_id)]
        activas = [f for f in base if f["estado"] == "activa"]
        datos = DatosEstado()
        for f in activas:
            datos.por_severidad[f["severidad"]] += 1
        datos.total_activas = len(activas)
        resumen: dict[tuple[str, str], dict] = {}
        for f in activas:
            r = resumen.setdefault((f["planta_id"], f["activo_id"]),
                                   {"planta_id": f["planta_id"], "activo_id": f["activo_id"], "activas": 0, "criticas": 0})
            r["activas"] += 1
            r["criticas"] += f["severidad"] == "critica"
        datos.resumen_por_activo = [resumen[k] for k in sorted(resumen)]
        pagina = [f for f in base
                  if (filtros.estado == "todas" or f["estado"] == filtros.estado)
                  and (not filtros.severidad or f["severidad"] == filtros.severidad)]
        pagina.sort(key=lambda f: f["id"])
        pagina.sort(key=lambda f: f["ultima_deteccion"], reverse=True)
        datos.total = len(pagina)
        datos.datos = pagina[filtros.offset:filtros.offset + filtros.limit]
        return datos


@pytest.fixture(scope="session")
def contrato() -> OpenAPI:
    return OpenAPI.from_file_path(str(RAIZ / "openapi.yaml"))


@pytest.fixture
def repo() -> RepositorioFalso:
    return RepositorioFalso()


@pytest.fixture
def cliente(repo: RepositorioFalso):
    if BASE_URL:
        with httpx.Client(base_url=BASE_URL, timeout=15) as c:
            yield c
        return
    app = create_app(Config(), repositorio=repo)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def validar(contrato: OpenAPI):
    """Valida una respuesta httpx contra la operación y el código de estado del contrato."""

    def _validar(resp: httpx.Response) -> httpx.Response:
        req = resp.request
        peticion = MockRequest(
            SERVIDOR_CONTRATO,
            req.method.lower(),
            req.url.path,
            args=dict(parse_qsl(req.url.query.decode() if isinstance(req.url.query, bytes) else req.url.query)),
            headers=dict(req.headers),
            data=req.content or None,
            content_type=req.headers.get("content-type", "application/json"),
        )
        respuesta = MockResponse(
            resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
            content_type=resp.headers.get("content-type", "").split(";")[0],
        )
        contrato.validate_response(peticion, respuesta)
        return resp

    return _validar

