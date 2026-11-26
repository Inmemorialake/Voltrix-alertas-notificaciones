"""Logs estructurados en JSON, una línea por evento."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        evento = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        campos = getattr(record, "campos", None)
        if isinstance(campos, dict):
            evento.update(campos)
        if record.exc_info:
            evento["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logs(nivel: str = "INFO") -> None:
    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(FormatoJson())
    raiz = logging.getLogger()
    raiz.handlers[:] = [manejador]
    raiz.setLevel(nivel)
    # Uvicorn usa sus propios handlers: se redirigen al formato JSON.
    for nombre in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nombre)
        logger.handlers[:] = []
        logger.propagate = True
