"""Modelos Pydantic que reflejan los esquemas de openapi.yaml."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

PATRON_IDENTIFICADOR = r"^[A-Za-z0-9_-]+$"
PATRON_EQUIPO = r"^equipo-[1-7]$"

Identificador = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=PATRON_IDENTIFICADOR)]
TipoActivo = Literal["panel_solar", "turbina", "banco_baterias"]
Severidad = Literal["advertencia", "critica"]
EstadoAlerta = Literal["activa", "resuelta"]
Modo = Literal["secuencial", "paralelo"]


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------- Entrada -------------------------------
class LecturaEntrada(Estricto):
    plantaId: Identificador
    activoId: Identificador
    tipoActivo: TipoActivo | None = None
    fechaHora: AwareDatetime
    metrica: str
    valor: float
    unidad: str


class SolicitudEvaluacion(Estricto):
    lecturas: Annotated[list[LecturaEntrada], Field(min_length=1, max_length=5000)] | None = None
    plantaId: Identificador | None = None
    desde: AwareDatetime | None = None
    hasta: AwareDatetime | None = None


# ------------------------------- Salida --------------------------------
class Alerta(Estricto):
    id: Identificador
    plantaId: Identificador
    activoId: Identificador
    tipoActivo: TipoActivo
    metrica: str
    valorObservado: float | None = None
    umbralAplicado: float | None = None
    severidad: Severidad
    estado: EstadoAlerta
    ocurrencias: Annotated[int, Field(ge=1)]
    primeraDeteccion: datetime
    ultimaDeteccion: datetime


class MetricasProcesamiento(Estricto):
    modo: Modo
    workers: Annotated[int, Field(ge=1)]
    elementos: Annotated[int, Field(ge=0)]
    duracionMs: Annotated[int, Field(ge=0)]


class ResultadoEvaluacion(Estricto):
    loteId: str
    lecturasEvaluadas: int
    alertasNuevas: int
    alertasActualizadas: int
    duplicadasEvitadas: int
    alertas: list[Alerta]
    metricas: MetricasProcesamiento


class PorSeveridad(Estricto):
    advertencia: int = 0
    critica: int = 0


class ResumenActivo(Estricto):
    plantaId: Identificador
    activoId: Identificador
    activas: int
    criticas: int


class EstadoAlertas(Estricto):
    generadoEn: datetime
    totalActivas: int
    porSeveridad: PorSeveridad
    resumenPorActivo: list[ResumenActivo]
    datos: list[Alerta]
    total: int
    limit: int
    offset: int


class Salud(Estricto):
    estado: Literal["disponible", "no_disponible"]
    baseDatos: Literal["ok", "error"]
    version: str
    tiempoActivoSeg: Annotated[int, Field(ge=0)]
