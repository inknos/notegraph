"""CLI logging: verbosity and noisy library suppression."""

from __future__ import annotations

import logging

# HTTP stacks log heavily at DEBUG; keep them quiet even when notegraph is verbose.
_NOISY_LOGGERS = (
    "urllib3",
    "urllib3.connectionpool",
    "urllib3.util.retry",
    "requests",
    "charset_normalizer",
)


def configure_cli_logging(*, verbose: bool) -> None:
    """Configure root logging for ``notegraph`` CLI once per process.

    With ``verbose=True``, root level is DEBUG so ``notegraph.*`` loggers emit
    diagnostics; third-party HTTP libraries stay at WARNING.

    Args:
        verbose: When True, enable DEBUG on the root logger.
    """
    root_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=root_level,
        format="%(levelname)s %(name)s: %(message)s",
        force=True,
    )
    warn_level = logging.WARNING
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(warn_level)
