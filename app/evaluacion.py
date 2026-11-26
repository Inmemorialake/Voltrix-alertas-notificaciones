"""Evaluación de lecturas contra umbrales.

Avance 1: la evaluación es secuencial y no persiste. `modo=paralelo` ya existe en el
contrato y en esta interfaz, pero delega en la misma evaluación de un hilo; su
implementación concurrente (workers, locks por franja y cola) llega en el Avance 2
(ver app/concurrencia.py).
"""

from __future__ import annotations

import statistics
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from app.modelos import Alerta, LecturaEntrada


@dataclass(frozen=True)
class Umbral:
    id: str
    tipo_activo: str
    metrica_entrada: str  # la que llega de Telemetría
    metrica: str  # la que se evalúa y se registra en la alerta
    operador: str  # gt | fuera_rango
    advertencia: float
    critico: float
    critico_inferior: float | None = None
    lecturas_minimas: int = 3


# Mismos valores que app/migraciones/002_semilla.sql (docs/diseno.md, sección 3).
UMBRALES: dict[tuple[str, str], Umbral] = {
    (u.tipo_activo, u.metrica_entrada): u
    for u in (
        Umbral("UMB-BB-TEMPERATURA", "banco_baterias", "temperatura", "temperatura", "gt", 40, 45),
        Umbral("UMB-PS-CAIDA", "panel_solar", "potencia", "caida_potencia", "gt", 20, 40),
        Umbral("UMB-TB-VIENTO", "turbina", "velocidad_viento", "velocidad_viento", "fuera_rango", 20, 25, 3),
    )
}

SEGMENTO_TIPO = {"PS": "panel_solar", "TB": "turbina", "BB": "banco_baterias"}


def tipo_de_activo(lectura: LecturaEntrada) -> str | None:
    """`tipoActivo` de la lectura o, si falta, el segmento del ID del Inventario (PL-002-BB-01)."""
    if lectura.tipoActivo:
        return lectura.tipoActivo
    for segmento in lectura.activoId.upper().split("-"):
        if segmento in SEGMENTO_TIPO:
            return SEGMENTO_TIPO[segmento]
    return None


def clasificar(umbral: Umbral, valor: float) -> tuple[str, float] | None:
    """Devuelve (severidad, umbral aplicado) o None si el valor está en rango."""
    if umbral.operador == "fuera_rango" and umbral.critico_inferior is not None and valor < umbral.critico_inferior:
        return "critica", umbral.critico_inferior
    if valor > umbral.critico:
        return "critica", umbral.critico
    if valor > umbral.advertencia:
        return "advertencia", umbral.advertencia
    return None


@dataclass
class Deteccion:
    umbral: Umbral
    plantaId: str
    activoId: str
    severidad: str
    umbral_aplicado: float
    valor: float
    fecha: datetime


@dataclass
class ResultadoLote:
    alertas: list[Alerta]
    lecturas_evaluadas: int
    alertas_actualizadas: int = 0
    duplicadas_evitadas: int = 0


def detectar(lecturas: list[LecturaEntrada]) -> list[Deteccion]:
    """Paso puro de evaluación: lectura por lectura, sin estado compartido."""
    # La caída de un panel se mide contra la mediana de su potencia en el lote.
    potencias: dict[str, list[float]] = defaultdict(list)
    for lec in lecturas:
        if lec.metrica == "potencia" and tipo_de_activo(lec) == "panel_solar":
            potencias[lec.activoId].append(lec.valor)
    medianas = {activo: statistics.median(v) for activo, v in potencias.items()}

    detecciones = []
    for lec in lecturas:
        tipo = tipo_de_activo(lec)
        umbral = UMBRALES.get((tipo, lec.metrica)) if tipo else None
        if umbral is None:
            continue
        valor = lec.valor
        if umbral.metrica == "caida_potencia":
            mediana = medianas.get(lec.activoId, 0)
            if mediana <= 0:
                continue
            valor = round(max(0.0, (mediana - lec.valor) / mediana * 100), 2)
        clase = clasificar(umbral, valor)
        if clase:
            detecciones.append(Deteccion(umbral, lec.plantaId, lec.activoId, clase[0], clase[1], valor, lec.fechaHora))
    return detecciones


def agrupar(detecciones: list[Deteccion]) -> list[Alerta]:
    """Crea una alerta por (activo, métrica, severidad) con al menos `lecturas_minimas` violaciones."""
    grupos: dict[tuple[str, str, str], list[Deteccion]] = defaultdict(list)
    for det in detecciones:
        grupos[(det.activoId, det.umbral.metrica, det.severidad)].append(det)

    alertas = []
    for (activo, metrica, severidad), dets in sorted(grupos.items()):
        umbral = dets[0].umbral
        if len(dets) < umbral.lecturas_minimas:
            continue
        dets.sort(key=lambda d: d.fecha)
        primera = dets[0].fecha.astimezone(timezone.utc)
        alertas.append(
            Alerta(
                id=f"ALR-{primera:%Y%m%d}-{uuid.uuid4().hex[:8]}",
                plantaId=dets[-1].plantaId,
                activoId=activo,
                tipoActivo=umbral.tipo_activo,
                metrica=metrica,
                valorObservado=dets[-1].valor,
                umbralAplicado=dets[-1].umbral_aplicado,
                severidad=severidad,
                estado="activa",
                ocurrencias=len(dets),
                primeraDeteccion=primera,
                ultimaDeteccion=dets[-1].fecha.astimezone(timezone.utc),
            )
        )
    return alertas


class Evaluador(ABC):
    modo: str

    @abstractmethod
    def evaluar(self, lecturas: list[LecturaEntrada], workers: int) -> ResultadoLote: ...


class EvaluadorSecuencial(Evaluador):
    """Línea base de un hilo (versión A del benchmark) y oráculo de resultados."""

    modo = "secuencial"

    def evaluar(self, lecturas: list[LecturaEntrada], workers: int = 1) -> ResultadoLote:
        return ResultadoLote(alertas=agrupar(detectar(lecturas)), lecturas_evaluadas=len(lecturas))


class EvaluadorParalelo(Evaluador):
    """Versión con control de concurrencia (versión C del benchmark).

    Avance 2: partir `lecturas` en `workers` bloques con ThreadPoolExecutor; cada worker
    registra violaciones en un `RegistroCompartido` (locks por franja) y encola en una
    `ColaNotificaciones`; un despachador persiste con INSERT ... ON CONFLICT.
    Avance 1: delega en la evaluación secuencial para que el contrato ya responda.
    """

    modo = "paralelo"

    def evaluar(self, lecturas: list[LecturaEntrada], workers: int) -> ResultadoLote:
        return EvaluadorSecuencial().evaluar(lecturas)


EVALUADORES: dict[str, Evaluador] = {"secuencial": EvaluadorSecuencial(), "paralelo": EvaluadorParalelo()}
