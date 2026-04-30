"""Tests for CLI logging configuration."""

from __future__ import annotations

import logging

from notegraph.logutil import configure_cli_logging


def test_configure_cli_logging_verbose_sets_root_debug() -> None:
    configure_cli_logging(verbose=True)
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_configure_cli_logging_quiet_sets_root_info() -> None:
    configure_cli_logging(verbose=False)
    root = logging.getLogger()
    assert root.level == logging.INFO
