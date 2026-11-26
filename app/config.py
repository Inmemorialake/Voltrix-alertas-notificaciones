"""Configuración del servicio. Solo se lee de variables de entorno."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app import __version__

RAIZ_REPO = Path(__file__).resolve().parent.parent


def _entero(nombre: str, defecto: int, minimo: int = 0) -> int:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        return defecto
    try:
        numero = int(valor)
    except ValueError as exc:
        raise ValueError(f"{nombre} debe ser un entero, se recibió {valor!r}") from exc
    if numero < minimo:
        raise ValueError(f"{nombre} debe ser >= {minimo}, se recibió {numero}")
    return numero


@dataclass(frozen=True)
class Config:
    database_url: str = "postgresql://voltrix:voltrix@localhost:5432/alertas"
    # Vacía: POST /alertas con plantaId usa lecturas de ejemplo en lugar de llamar a Telemetría.
    telemetria_url: str = ""
    # Workers por defecto para modo=paralelo cuando la petición no envía `workers`.
    workers: int = 4
    # Peticiones simultáneas admitidas antes de responder 429 SOBRECARGA.
    max_concurrencia: int = 16
    puerto: int = 8080
    nivel_log: str = "INFO"
    openapi_path: Path = RAIZ_REPO / "openapi.yaml"
    # Página Redoc (la misma de GitHub Pages) que se sirve en /docs.
    docs_path: Path = RAIZ_REPO / "index.html"
    version: str = __version__

    @classmethod
    def desde_entorno(cls) -> "Config":
        defecto = cls()
        return cls(
            database_url=os.environ.get("DATABASE_URL", defecto.database_url),
            telemetria_url=os.environ.get("TELEMETRIA_URL", "").strip().rstrip("/"),
            workers=min(_entero("WORKERS", defecto.workers, minimo=1), 64),
            max_concurrencia=_entero("MAX_CONCURRENCIA", defecto.max_concurrencia, minimo=1),
            puerto=_entero("PUERTO", defecto.puerto, minimo=1),
            nivel_log=os.environ.get("NIVEL_LOG", defecto.nivel_log).upper(),
            openapi_path=Path(os.environ.get("OPENAPI_PATH", defecto.openapi_path)),
            docs_path=Path(os.environ.get("DOCS_PATH", defecto.docs_path)),
        )
