"""Cliente de Telemetría de Plantas (Equipo 2).

Con TELEMETRIA_URL vacía (Avance 1, sin el servicio del Equipo 2 desplegado) se generan
lecturas de ejemplo deterministas para la planta y la ventana pedidas.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

import httpx
from pydantic import ValidationError

from app.modelos import LecturaEntrada

log = logging.getLogger("alertas.telemetria")

MAX_LECTURAS = 5000
TIPOS = ("banco_baterias", "panel_solar", "turbina")


class DependenciaFallida(Exception):
    def __init__(self, mensaje: str, problema: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.problema = problema


class ClienteTelemetria:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def lecturas(self, planta_id: str, desde: datetime, hasta: datetime, request_id: str) -> list[LecturaEntrada]:
        if not self.base_url:
            return lecturas_ejemplo(planta_id, desde, hasta)
        ruta = f"/telemetria/{planta_id}"
        cabeceras = {"X-Equipo-Consumidor": "equipo-3", "X-Request-Id": request_id}
        resultado: list[LecturaEntrada] = []
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, headers=cabeceras) as cliente:
                for tipo in TIPOS:
                    offset: str | None = "0"
                    while offset is not None and len(resultado) < MAX_LECTURAS:
                        resp = cliente.get(
                            ruta,
                            params={"desde": desde.isoformat(), "hasta": hasta.isoformat(), "tipoActivo": tipo,
                                    "limit": 200, "offset": offset},
                        )
                        if resp.status_code != 200:
                            raise DependenciaFallida(
                                f"Telemetría de Plantas respondió {resp.status_code}.",
                                f"GET {ruta} respondió {resp.status_code}",
                            )
                        cuerpo = resp.json()
                        filas = cuerpo.get("datos", []) if isinstance(cuerpo, dict) else cuerpo
                        for fila in filas:
                            resultado.append(LecturaEntrada.model_validate({**fila, "tipoActivo": tipo}))
                        offset = resp.headers.get("X-Next-Offset") or None
        except httpx.HTTPError as exc:
            raise DependenciaFallida("Telemetría de Plantas no respondió.", f"GET {ruta}: {exc}") from exc
        except (ValueError, ValidationError) as exc:
            raise DependenciaFallida(
                "Telemetría de Plantas respondió con un formato inesperado.", f"GET {ruta}: {exc}"
            ) from exc
        return resultado[:MAX_LECTURAS]


def lecturas_ejemplo(planta_id: str, desde: datetime, hasta: datetime) -> list[LecturaEntrada]:
    """Una lectura cada 5 minutos por activo; el banco de baterías se sobrecalienta al final."""
    azar = random.Random(planta_id)
    paso = timedelta(minutes=5)
    n = max(1, min(int((hasta - desde) / paso), MAX_LECTURAS // 3))
    lecturas = []
    for i in range(n):
        t = desde + i * paso
        progreso = i / max(n - 1, 1)
        filas = [
            (f"{planta_id}-BB-01", "banco_baterias", "temperatura", round(38 + 9 * progreso + azar.uniform(-0.5, 0.5), 1), "C"),
            (f"{planta_id}-PS-07", "panel_solar", "potencia", round(azar.uniform(950, 1050), 1), "W"),
            (f"{planta_id}-TB-03", "turbina", "velocidad_viento", round(azar.uniform(8, 18), 1), "m/s"),
        ]
        for activo, tipo, metrica, valor, unidad in filas:
            lecturas.append(
                LecturaEntrada(plantaId=planta_id, activoId=activo, tipoActivo=tipo, fechaHora=t,
                               metrica=metrica, valor=valor, unidad=unidad)
            )
    return lecturas
