"""Punto de entrada: `python -m app`."""

import uvicorn

from app.config import Config
from app.logs import configurar_logs
from app.main import create_app


def main() -> None:
    config = Config.desde_entorno()
    configurar_logs(config.nivel_log)
    uvicorn.run(
        create_app(config),
        host="0.0.0.0",
        port=config.puerto,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
