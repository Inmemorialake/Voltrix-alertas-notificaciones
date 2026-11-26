"""Acceso a PostgreSQL: migraciones y consulta del estado de las alertas."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

log = logging.getLogger("alertas.repositorio")

DIR_MIGRACIONES = Path(__file__).resolve().parent / "migraciones"
# Clave del advisory lock: evita que dos réplicas apliquen las migraciones a la vez.
LOCK_MIGRACIONES = 750_023_003


class BaseDatosNoDisponible(Exception):
    """La base de datos no respondió o falló la consulta."""


@dataclass(frozen=True)
class FiltrosEstado:
    planta_id: str | None = None
    activo_id: str | None = None
    severidad: str | None = None
    estado: str = "activa"  # activa | resuelta | todas
    limit: int = 50
    offset: int = 0


@dataclass
class DatosEstado:
    total_activas: int = 0
    por_severidad: dict[str, int] = field(default_factory=lambda: {"advertencia": 0, "critica": 0})
    resumen_por_activo: list[dict[str, Any]] = field(default_factory=list)
    datos: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0


class RepositorioAlertas(Protocol):
    def abrir(self) -> None: ...
    def cerrar(self) -> None: ...
    def ping(self) -> None: ...
    def consultar_estado(self, filtros: FiltrosEstado) -> DatosEstado: ...


_COLUMNAS_ALERTA = """
    id, planta_id, activo_id, tipo_activo, metrica, valor_observado, umbral_aplicado,
    severidad, estado, ocurrencias, primera_deteccion, ultima_deteccion
"""


class RepositorioPostgres:
    def __init__(self, dsn: str, max_conexiones: int = 5, timeout: float = 3.0) -> None:
        self._timeout = timeout
        self._migrado = False
        self._lock_migracion = threading.Lock()
        self._pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=max_conexiones,
            open=False,
            timeout=timeout,
            check=ConnectionPool.check_connection,
            kwargs={"connect_timeout": int(timeout), "options": "-c TimeZone=UTC", "application_name": "alertas"},
            name="alertas",
        )

    # ----------------------------- ciclo de vida -----------------------------
    def abrir(self) -> None:
        self._pool.open(wait=False)
        try:
            self.migrar()
        except BaseDatosNoDisponible:
            log.warning("base de datos no disponible al iniciar; se reintenta en /health")

    def cerrar(self) -> None:
        self._pool.close()

    def migrar(self) -> None:
        if self._migrado:
            return
        with self._lock_migracion:
            if self._migrado:
                return
            try:
                with self._pool.connection(timeout=self._timeout) as conn:
                    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_MIGRACIONES,))
                    try:
                        aplicadas = self._aplicar_migraciones(conn)
                    finally:
                        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_MIGRACIONES,))
                        conn.commit()
            except (psycopg.Error, PoolTimeout) as exc:
                raise BaseDatosNoDisponible(str(exc)) from exc
            self._migrado = True
            log.info("migraciones al día", extra={"campos": {"aplicadas": aplicadas}})

    @staticmethod
    def _aplicar_migraciones(conn: psycopg.Connection) -> list[str]:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migracion ("
            " version text PRIMARY KEY, aplicada_en timestamptz NOT NULL DEFAULT now())"
        )
        conn.commit()
        hechas = {fila[0] for fila in conn.execute("SELECT version FROM schema_migracion")}
        aplicadas = []
        for archivo in sorted(DIR_MIGRACIONES.glob("*.sql")):
            if archivo.name in hechas:
                continue
            with conn.transaction():
                conn.execute(archivo.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migracion (version) VALUES (%s)", (archivo.name,))
            aplicadas.append(archivo.name)
        conn.commit()
        return aplicadas

    # -------------------------------- consultas -------------------------------
    def ping(self) -> None:
        self.migrar()
        try:
            with self._pool.connection(timeout=self._timeout) as conn:
                conn.execute("SELECT 1")
        except (psycopg.Error, PoolTimeout) as exc:
            raise BaseDatosNoDisponible(str(exc)) from exc

    def consultar_estado(self, filtros: FiltrosEstado) -> DatosEstado:
        self.migrar()
        # Filtros de planta y activo: aplican a totales, porSeveridad y resumenPorActivo.
        base, params = ["TRUE"], []
        if filtros.planta_id:
            base.append("planta_id = %s")
            params.append(filtros.planta_id)
        if filtros.activo_id:
            base.append("activo_id = %s")
            params.append(filtros.activo_id)
        where_base = " AND ".join(base)

        # Filtros de la página: además, estado y severidad.
        pagina, params_pagina = list(base), list(params)
        if filtros.estado != "todas":
            pagina.append("estado = %s")
            params_pagina.append(filtros.estado)
        if filtros.severidad:
            pagina.append("severidad = %s")
            params_pagina.append(filtros.severidad)
        where_pagina = " AND ".join(pagina)

        try:
            with self._pool.connection(timeout=self._timeout) as conn:
                with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
                    # Una sola instantánea para que totales y página sean coherentes entre sí.
                    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    datos = DatosEstado()
                    cur.execute(
                        f"SELECT severidad, count(*) AS n FROM alerta"
                        f" WHERE estado = 'activa' AND {where_base} GROUP BY severidad",
                        params,
                    )
                    for fila in cur.fetchall():
                        datos.por_severidad[fila["severidad"]] = fila["n"]
                    datos.total_activas = sum(datos.por_severidad.values())

                    cur.execute(
                        f"SELECT planta_id, activo_id, count(*) AS activas,"
                        f" count(*) FILTER (WHERE severidad = 'critica') AS criticas"
                        f" FROM alerta WHERE estado = 'activa' AND {where_base}"
                        f" GROUP BY planta_id, activo_id ORDER BY planta_id, activo_id",
                        params,
                    )
                    datos.resumen_por_activo = cur.fetchall()

                    cur.execute(f"SELECT count(*) AS n FROM alerta WHERE {where_pagina}", params_pagina)
                    datos.total = cur.fetchone()["n"]

                    cur.execute(
                        f"SELECT {_COLUMNAS_ALERTA} FROM alerta WHERE {where_pagina}"
                        f" ORDER BY ultima_deteccion DESC, id LIMIT %s OFFSET %s",
                        [*params_pagina, filtros.limit, filtros.offset],
                    )
                    datos.datos = cur.fetchall()
                return datos
        except (psycopg.Error, PoolTimeout) as exc:
            raise BaseDatosNoDisponible(str(exc)) from exc
