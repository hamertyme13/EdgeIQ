"""Shared runtime logging configuration for EdgeIQ entry points."""
from __future__ import annotations

import logging
import os

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging() -> None:
    """Configure application logs once, honoring ``EDGEIQ_LOG_LEVEL``."""
    level_name = os.getenv("EDGEIQ_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format=_FORMAT)
    else:
        root.setLevel(level)
