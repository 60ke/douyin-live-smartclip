from __future__ import annotations

from typing import Any

from liveclip.observability.logging import get_logger as _get_logger
from liveclip.observability.logging import setup_logging as _setup_logging


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output for production, console for dev."""
    _setup_logging(log_level)


def get_logger(name: str = "liveclip") -> Any:
    """Return a structlog BoundLogger bound to *name*."""
    return _get_logger(name)


__all__ = ["get_logger", "setup_logging"]
