from __future__ import annotations

import logging
import os
import sys

import structlog
from structlog.stdlib import BoundLogger


def _is_dev_mode() -> bool:
    """Heuristic: treat as development when no explicit LOG_FORMAT=JSON."""
    return os.environ.get("LOG_FORMAT", "").upper() != "JSON"


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output for production, console for dev.

    Args:
        log_level: Standard Python log level name (DEBUG, INFO, ...).
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)

    shared_processors: list[structlog.types.Processor] = [
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
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if _is_dev_mode():
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


def get_logger(name: str = "liveclip") -> BoundLogger:
    """Return a structlog BoundLogger bound to *name*.

    The returned logger supports structured context via ``.bind()``::

        log = get_logger("pipeline")
        log = log.bind(run_id=42, room_id=1001, step_name="transcribe")
        log.info("step started")
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
