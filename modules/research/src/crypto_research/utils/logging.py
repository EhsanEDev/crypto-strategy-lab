"""Logging setup: clear, actionable, [LEVEL]-prefixed."""

from __future__ import annotations

import logging

_FORMAT = "[%(levelname)s] %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once (idempotent)."""
    root = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        for handler in root.handlers:
            handler.setLevel(level.upper())
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
