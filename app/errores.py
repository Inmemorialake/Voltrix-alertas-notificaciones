"""Errores con el esquema común `Error` (codigo, mensaje, requestId, detalles)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("alertas.errores")


class ErrorApi(Exception):
    def __init__(
        self,
        status: int,
        codigo: str,
        mensaje: str,
        detalles: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalles = detalles
        self.headers = headers


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = str(uuid.uuid4())
        request.state.request_id = rid
    return rid


def respuesta_error(
    request: Request,
    status: int,
    codigo: str,
    mensaje: str,
    detalles: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = request_id(request)
    cuerpo: dict[str, Any] = {"codigo": codigo, "mensaje": mensaje, "requestId": rid}
    if detalles:
        cuerpo["detalles"] = detalles
    return JSONResponse(cuerpo, status_code=status, headers={**(headers or {}), "X-Request-Id": rid})


# Mensajes en español para los errores de validación más comunes de Pydantic.
_PROBLEMAS = {
    "missing": "es obligatorio",
    "extra_forbidden": "campo no permitido por el contrato",
    "json_invalid": "el cuerpo no es JSON válido",
    "string_pattern_mismatch": "no cumple el patrón {pattern}",
    "string_too_short": "debe tener al menos {min_length} caracteres",
    "string_too_long": "debe tener como máximo {max_length} caracteres",
    "too_short": "debe tener al menos {min_length} elementos",
    "too_long": "debe tener como máximo {max_length} elementos",
    "literal_error": "debe ser uno de: {expected}",
    "greater_than_equal": "debe ser mayor o igual que {ge}",
    "less_than_equal": "debe ser menor o igual que {le}",
    "int_parsing": "debe ser un entero",
    "int_type": "debe ser un entero",
    "float_parsing": "debe ser un número",
    "float_type": "debe ser un número",
    "string_type": "debe ser texto",
    "list_type": "debe ser una lista",
    "model_attributes_type": "debe ser un objeto",
    "dict_type": "debe ser un objeto",
    "timezone_aware": "debe incluir zona horaria (RFC 3339)",
    "datetime_from_date_parsing": "debe ser una fecha RFC 3339 con zona horaria",
    "datetime_parsing": "debe ser una fecha RFC 3339 con zona horaria",
    "datetime_type": "debe ser una fecha RFC 3339 con zona horaria",
}


def _campo(loc: tuple[Any, ...]) -> str:
    partes = list(loc)
    if partes and partes[0] in ("body", "query", "path", "header"):
        origen = partes.pop(0)
        if origen == "header" and partes:
            return str(partes[0]).title()
    if not partes:
        return "cuerpo"
    texto = ""
    for parte in partes:
        texto += f"[{parte}]" if isinstance(parte, int) else (f".{parte}" if texto else str(parte))
    return texto


def _problema(error: dict[str, Any]) -> str:
    plantilla = _PROBLEMAS.get(error.get("type", ""))
    if plantilla is None:
        return error.get("msg", "valor inválido")
    try:
        return plantilla.format(**(error.get("ctx") or {}))
    except (KeyError, IndexError):
        return plantilla


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorApi)
    async def _error_api(request: Request, exc: ErrorApi) -> JSONResponse:
        return respuesta_error(request, exc.status, exc.codigo, exc.mensaje, exc.detalles, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
        detalles = [{"campo": _campo(tuple(e.get("loc", ()))), "problema": _problema(e)} for e in exc.errors()]
        return respuesta_error(request, 400, "SOLICITUD_INVALIDA", "La solicitud no cumple el contrato.", detalles)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return respuesta_error(request, 404, "NO_ENCONTRADO", "La ruta no existe.")
        if exc.status_code == 405:
            return respuesta_error(request, 405, "SOLICITUD_INVALIDA", "Método no permitido para esta ruta.")
        codigo = "SOLICITUD_INVALIDA" if exc.status_code < 500 else "ERROR_INTERNO"
        return respuesta_error(request, exc.status_code, codigo, str(exc.detail))

    @app.exception_handler(Exception)
    async def _interno(request: Request, exc: Exception) -> JSONResponse:
        log.exception("error no controlado", extra={"campos": {"requestId": request_id(request)}})
        return respuesta_error(request, 500, "ERROR_INTERNO", "Error interno del servicio.")
