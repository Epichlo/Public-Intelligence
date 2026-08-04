"""Logging configuration for the Public Intelligence Node."""

import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """Configure the root logger with a standardized format and stdout handler.

    Args:
        log_level: The logging level to set (DEBUG, INFO, WARNING, ERROR).
    """
    log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()

    # Clear existing handlers to prevent duplicate logs
    for existing_handler in list(root_logger.handlers):
        root_logger.removeHandler(existing_handler)

    root_logger.addHandler(handler)

    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    root_logger.setLevel(numeric_level)

    # Set logger level for third-party libraries
    logging.getLogger("uvicorn.error").setLevel(numeric_level)
    logging.getLogger("uvicorn.access").setLevel(numeric_level)
