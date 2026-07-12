"""Tests for node logging configuration."""

import logging

from node.core.logging import setup_logging


def test_setup_logging() -> None:
    """Verify that logging setup does not raise errors.

    Also checks that it sets the root logger level.
    """
    setup_logging("DEBUG")
    root_logger = logging.getLogger()
    assert root_logger.level == logging.DEBUG

    setup_logging("INFO")
    assert root_logger.level == logging.INFO

    # Test invalid level fallback
    setup_logging("INVALID_LEVEL")
    assert root_logger.level == logging.INFO
