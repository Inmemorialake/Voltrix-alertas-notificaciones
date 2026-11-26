"""X-Request-Id, log JSON por petición y límite de peticiones simultáneas (429)."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.errores import respuesta_error

log = logging.getLogger("alertas.http")

# Operación: no cuentan contra el límite, para que las sondas no fallen bajo carga.
RUTAS_EXENTAS = frozenset({"/health", "/openapi.yaml", "/docs", "/"})
RETRY_AFTER_SEG = 1


class MiddlewareSolicitudes(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, max_concurrencia: int) -> None:
        super().__init__(app)
        self.max_concurrencia = max_concurrencia
        # Solo se modifica desde el event loop (un hilo), así que no necesita lock.
        self.en_curso = 0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = str(uuid.uuid4())
        request.state.request_id = rid
        inicio = time.perf_counter()
        limitada = request.url.path not in RUTAS_EXENTAS
        status = 500
        try:
            if limitada and self.en_curso >= self.max_concurrencia:
                response = respuesta_error(
                    request, 429, "SOBRECARGA",
                    "El servicio alcanzó su máximo de peticiones simultáneas.",
                    headers={"Retry-After": str(RETRY_AFTER_SEG)},
                )
            else:
                if limitada:
                    self.en_curso += 1
                try:
                    response = await call_next(request)
                finally:
                    if limitada:
                        self.en_curso -= 1
            response.headers["X-Request-Id"] = rid
            status = response.status_code
            return response
        finally:
            log.info(
                "solicitud",
                extra={
                    "campos": {
                        "requestId": rid,
                        "equipoConsumidor": request.headers.get("X-Equipo-Consumidor"),
                        "metodo": request.method,
                        "ruta": request.url.path,
                        "query": request.url.query or None,
                        "status": status,
                        "duracionMs": round((time.perf_counter() - inicio) * 1000, 2),
                    }
                },
            )
