from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(data_dir: str | Path) -> logging.Logger:
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    log_path = (directory / "vm-clone.log").resolve()
    logger = logging.getLogger("vm-clone")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    already_configured = any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == log_path
        for handler in logger.handlers
    )
    if not already_configured:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger

