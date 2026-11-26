"""API REST del servicio Alertas y Notificaciones. El contrato vigente es openapi.yaml."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, Response

from app.config import Config
from app.errores import ErrorApi, registrar_manejadores, request_id
from app.evaluacion import EVALUADORES
from app.middleware import MiddlewareSolicitudes
from app.modelos import (
    PATRON_EQUIPO,
    PATRON_IDENTIFICADOR,
    Alerta,
    EstadoAlertas,
    MetricasProcesamiento,
    Modo,
    PorSeveridad,
    ResultadoEvaluacion,
    ResumenActivo,
    Salud,
    Severidad,
    SolicitudEvaluacion,
)
from app.repositorio import BaseDatosNoDisponible, FiltrosEstado, RepositorioAlertas, RepositorioPostgres
from app.telemetria import ClienteTelemetria, DependenciaFallida

log = logging.getLogger("alertas.api")

EquipoConsumidor = Annotated[str | None, Header(alias="X-Equipo-Consumidor", pattern=PATRON_EQUIPO)]
FiltroId = Annotated[str | None, Query(min_length=1, max_length=64, pattern=PATRON_IDENTIFICADOR)]


def _sin_base_datos() -> ErrorApi:
    return ErrorApi(503, "NO_DISPONIBLE", "No hay conexión con la base de datos.")


def _fila_a_alerta(fila: dict) -> Alerta:
    return Alerta(
        id=fila["id"],
        plantaId=fila["planta_id"],
        activoId=fila["activo_id"],
        tipoActivo=fila["tipo_activo"],
        metrica=fila["metrica"],
        valorObservado=fila["valor_observado"],
        umbralAplicado=fila["umbral_aplicado"],
        severidad=fila["severidad"],
        estado=fila["estado"],
        ocurrencias=fila["ocurrencias"],
        primeraDeteccion=fila["primera_deteccion"].astimezone(timezone.utc),
        ultimaDeteccion=fila["ultima_deteccion"].astimezone(timezone.utc),
    )


def _json(modelo) -> dict:
    return modelo.model_dump(mode="json", exclude_none=True)


def create_app(
    config: Config | None = None,
    repositorio: RepositorioAlertas | None = None,
    telemetria: ClienteTelemetria | None = None,
) -> FastAPI:
    config = config or Config.desde_entorno()
    repo: RepositorioAlertas = repositorio or RepositorioPostgres(config.database_url)
    cliente_telemetria = telemetria or ClienteTelemetria(config.telemetria_url)
    contrato = config.openapi_path.read_bytes()
    inicio = time.monotonic()

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI):
        repo.abrir()
        log.info(
            "servicio iniciado",
            extra={"campos": {"version": config.version, "workers": config.workers,
                              "maxConcurrencia": config.max_concurrencia,
                              "telemetria": config.telemetria_url or "lecturas de ejemplo"}},
        )
        yield
        repo.cerrar()

    # Se desactiva el OpenAPI autogenerado: el contrato es openapi.yaml, servido tal cual.
    app = FastAPI(
        title="Voltrix Energy · Alertas y Notificaciones",
        version=config.version,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        lifespan=ciclo_de_vida,
    )
    registrar_manejadores(app)
    app.add_middleware(MiddlewareSolicitudes, max_concurrencia=config.max_concurrencia)

    @app.post("/alertas")
    def evaluar_lote_alertas(
        request: Request,
        solicitud: Annotated[SolicitudEvaluacion, Body()],
        _equipo: EquipoConsumidor = None,
        modo: Annotated[Modo, Query()] = "paralelo",
        workers: Annotated[int | None, Query(ge=1, le=64)] = None,
    ) -> JSONResponse:
        rid = request_id(request)
        por_telemetria = any(v is not None for v in (solicitud.plantaId, solicitud.desde, solicitud.hasta))
        if solicitud.lecturas is not None and por_telemetria:
            raise ErrorApi(400, "SOLICITUD_INVALIDA", "La solicitud no cumple el contrato.",
                           [{"campo": "lecturas", "problema": "envíe 'lecturas' o 'plantaId', no ambos"}])
        if solicitud.lecturas is None:
            faltan = [c for c in ("plantaId", "desde", "hasta") if getattr(solicitud, c) is None]
            if faltan:
                raise ErrorApi(400, "SOLICITUD_INVALIDA", "La solicitud no cumple el contrato.",
                               [{"campo": c, "problema": "envíe 'lecturas' o 'plantaId' con 'desde' y 'hasta'"}
                                for c in faltan])
            if solicitud.hasta <= solicitud.desde:
                raise ErrorApi(400, "SOLICITUD_INVALIDA", "La solicitud no cumple el contrato.",
                               [{"campo": "hasta", "problema": "debe ser posterior a 'desde'"}])

        if solicitud.lecturas is not None:
            lecturas = solicitud.lecturas
        else:
            try:
                lecturas = cliente_telemetria.lecturas(solicitud.plantaId, solicitud.desde, solicitud.hasta, rid)
            except DependenciaFallida as exc:
                raise ErrorApi(502, "DEPENDENCIA_FALLIDA", exc.mensaje,
                               [{"campo": "equipo-2", "problema": exc.problema}]) from exc

        n_workers = 1 if modo == "secuencial" else (workers or config.workers)
        t0 = time.perf_counter()
        resultado = EVALUADORES[modo].evaluar(lecturas, n_workers)
        duracion_ms = int((time.perf_counter() - t0) * 1000)

        respuesta = ResultadoEvaluacion(
            loteId=str(uuid.uuid4()),
            lecturasEvaluadas=resultado.lecturas_evaluadas,
            alertasNuevas=len(resultado.alertas),
            alertasActualizadas=resultado.alertas_actualizadas,
            duplicadasEvitadas=resultado.duplicadas_evitadas,
            alertas=resultado.alertas,
            metricas=MetricasProcesamiento(modo=modo, workers=n_workers, elementos=len(lecturas),
                                           duracionMs=duracion_ms),
        )
        log.info(
            "lote evaluado",
            extra={"campos": {"requestId": rid, "loteId": respuesta.loteId, "modo": modo, "workers": n_workers,
                              "elementos": len(lecturas), "duracionMs": duracion_ms,
                              "alertasNuevas": respuesta.alertasNuevas,
                              "duplicadasEvitadas": respuesta.duplicadasEvitadas,
                              "origen": "cuerpo" if solicitud.lecturas is not None else "telemetria"}},
        )
        return JSONResponse(_json(respuesta))

    @app.get("/alertas/estado")
    def consultar_estado_alertas(
        _equipo: EquipoConsumidor = None,
        plantaId: FiltroId = None,
        activoId: FiltroId = None,
        severidad: Annotated[Severidad | None, Query()] = None,
        estado: Annotated[Literal["activa", "resuelta", "todas"], Query()] = "activa",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> JSONResponse:
        filtros = FiltrosEstado(plantaId, activoId, severidad, estado, limit, offset)
        try:
            datos = repo.consultar_estado(filtros)
        except BaseDatosNoDisponible as exc:
            log.warning("consulta sin base de datos", extra={"campos": {"error": str(exc)}})
            raise _sin_base_datos() from exc
        respuesta = EstadoAlertas(
            generadoEn=datetime.now(timezone.utc).replace(microsecond=0),
            totalActivas=datos.total_activas,
            porSeveridad=PorSeveridad(**datos.por_severidad),
            resumenPorActivo=[
                ResumenActivo(plantaId=r["planta_id"], activoId=r["activo_id"], activas=r["activas"],
                              criticas=r["criticas"])
                for r in datos.resumen_por_activo
            ],
            datos=[_fila_a_alerta(f) for f in datos.datos],
            total=datos.total,
            limit=limit,
            offset=offset,
        )
        return JSONResponse(_json(respuesta))

    # HEAD además de GET: lo usan monitores y `curl -I`.
    @app.api_route("/health", methods=["GET", "HEAD"])
    def consultar_salud() -> JSONResponse:
        try:
            repo.ping()
            ok = True
        except BaseDatosNoDisponible as exc:
            log.warning("health sin base de datos", extra={"campos": {"error": str(exc)}})
            ok = False
        salud = Salud(
            estado="disponible" if ok else "no_disponible",
            baseDatos="ok" if ok else "error",
            version=config.version,
            tiempoActivoSeg=int(time.monotonic() - inicio),
        )
        return JSONResponse(_json(salud), status_code=200 if ok else 503)

    @app.api_route("/openapi.yaml", methods=["GET", "HEAD"])
    def obtener_contrato() -> Response:
        return Response(contrato, media_type="application/yaml")

    return app
