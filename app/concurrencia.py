"""Interfaces de los recursos compartidos del núcleo concurrente (Avance 2).

Ver docs/diseno.md, sección 5. Aquí solo se fija el contrato interno para que el
evaluador paralelo, el benchmark y las pruebas de carrera trabajen contra lo mismo.
"""

from __future__ import annotations

from typing import Protocol

from app.modelos import Alerta

# Locks por franja: el activo usa el lock de índice hash(activoId) % NUM_FRANJAS.
NUM_FRANJAS = 64


class ColaLlena(Exception):
    """La cola de notificaciones alcanzó su tamaño máximo: la API responde 429 SOBRECARGA."""


class RegistroCompartido(Protocol):
    """Contadores de violaciones por activo y registro de alertas activas.

    Implementación prevista: dict en memoria + `threading.Lock` por franja. Comprobar y
    crear la alerta ocurre bajo el mismo lock, así que no hay notificaciones duplicadas.
    """

    def registrar_violacion(self, activo_id: str, metrica: str, severidad: str) -> int:
        """Incrementa el contador de forma atómica y devuelve el valor nuevo."""
        ...

    def crear_o_actualizar(self, alerta: Alerta) -> bool:
        """Crea la alerta si no existe una activa con la misma clave. True si es nueva."""
        ...


class ColaNotificaciones(Protocol):
    """Cola thread-safe (`queue.Queue(maxsize)`) entre workers y despachador."""

    def encolar(self, alerta: Alerta) -> None:
        """Lanza ColaLlena si no hay espacio (no bloquea al worker)."""
        ...

    def tamano(self) -> int: ...
