from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.persistence.logging_config import configure_logging  # noqa: E402


def test_configure_logging_writes_to_the_user_data_directory(tmp_path):
    logger = configure_logging(tmp_path)
    logger.info("startup check")
    for handler in logger.handlers:
        handler.flush()

    log_path = tmp_path / "vm-clone.log"
    assert log_path.exists()
    assert "startup check" in log_path.read_text(encoding="utf-8")

