"""Centralized logging configuration for Aeternus.

Call ``setup_logging()`` once at application startup (CLI or gateway).
All modules should use ``logging.getLogger(__name__)`` for their loggers.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional


def setup_logging(
    level: Optional[str] = None,
    log_dir: Optional[str] = None,
    json_format: bool = False,
    max_bytes: int = 10_000_000,
    backup_count: int = 5,
) -> None:
    """Configure root logger with console + rotating file handlers.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR). Defaults to
            env var ``LOG_LEVEL`` or ``"INFO"``.
        log_dir: Directory for log files. Defaults to env var
            ``LOG_DIR`` or ``"logs/"``.
        json_format: If True, use JSON-structured log lines.
        max_bytes: Max bytes per log file before rotation.
        backup_count: Number of rotated log files to keep.
    """
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    resolved_dir = Path(log_dir or os.getenv("LOG_DIR", "logs"))
    resolved_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return  # Already configured — avoid duplicate handlers.
    root.setLevel(getattr(logging, resolved_level, logging.INFO))

    if json_format:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S")

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        str(resolved_dir / "aeternus.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Execution-specific log file
    exec_handler = logging.handlers.RotatingFileHandler(
        str(resolved_dir / "execution.log"),
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    exec_handler.setFormatter(formatter)
    exec_handler.setLevel(logging.INFO)
    logging.getLogger("tradingagents.graph.paper_execution").addHandler(exec_handler)
