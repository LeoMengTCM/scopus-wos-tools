from __future__ import annotations

import logging


LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str | int = "INFO") -> int:
    """Configure root logging once and return the resolved numeric level."""
    numeric_level = getattr(logging, str(level).upper(), level)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(
            level=numeric_level,
            format=LOG_FORMAT,
            datefmt=LOG_DATE_FORMAT,
        )

    root_logger.setLevel(numeric_level)
    return int(numeric_level)
