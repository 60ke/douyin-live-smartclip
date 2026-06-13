"""API 服务器管理命令。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
import structlog
import typer

app = typer.Typer(help="API server management")


def _uvicorn_log_config() -> dict[str, object]:
    """构造与 structlog 兼容的 uvicorn 日志配置。

    让 uvicorn 内部日志也通过 structlog 输出，避免 root logger 被覆盖。
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "structlog.stdlib.ProcessorFormatter",
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.dev.ConsoleRenderer()
                    if os.environ.get("LOG_FORMAT", "").upper() != "JSON"
                    else structlog.processors.JSONRenderer(),
                ],
                "foreign_pre_chain": [
                    structlog.contextvars.merge_contextvars,
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.add_logger_name,
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.CallsiteParameterAdder(
                        {
                            structlog.processors.CallsiteParameter.FILENAME,
                            structlog.processors.CallsiteParameter.LINENO,
                        }
                    ),
                ],
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
) -> None:
    """Start the API server."""
    from liveclip.config import apply_runtime_environment, ensure_directories, load_settings
    from liveclip.observability import setup_logging

    load_dotenv()

    config_path = Path(config).resolve() if config else None
    if config_path is not None:
        os.environ["LIVECLIP_CONFIG"] = str(config_path)

    settings = load_settings(config_path)
    apply_runtime_environment(settings)
    ensure_directories(settings)
    setup_logging()

    import uvicorn

    uvicorn.run(
        "liveclip.api.app:create_app",
        host=host or settings.server.host,
        port=port or settings.server.port,
        factory=True,
        reload=reload,
        log_config=_uvicorn_log_config(),
    )
