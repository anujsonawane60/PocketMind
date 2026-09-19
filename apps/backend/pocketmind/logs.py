"""Logging that is safe to share.

PRD section 55 forbids logging passwords, keys, vault contents, chat messages,
and document contents. Rather than trusting every call site to remember that,
a filter scrubs anything that looks like a credential on its way out, and the
helpers below are the only sanctioned way to describe user content in a log
line.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "pocketmind"

_REDACTED = "[redacted]"

# Patterns are deliberately broad. A false positive costs a log line; a false
# negative writes a secret to a file the user may email to a maintainer.
_PATTERNS = (
    re.compile(r"(?i)\b(password|passphrase|secret|token|api[_-]?key|authorization)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\b(?:sk|pk|ghp|gho|xox[baprs])-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact(record.getMessage())
        record.args = ()
        return True


def _redact(message: str) -> str:
    for pattern in _PATTERNS:
        message = pattern.sub(_REDACTED, message)
    return message


_configured = False


def configure(log_file: Path | None = None, *, level: int = logging.INFO) -> logging.Logger:
    """Attach console logging, plus file logging once a drive is known.

    Safe to call repeatedly: the console handler is installed once, and the
    file handler is swapped when the active installation changes.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    if not _configured:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        console.addFilter(RedactingFilter())
        logger.addHandler(console)
        _configured = True

    if log_file is not None:
        for handler in list(logger.handlers):
            if isinstance(handler, RotatingFileHandler):
                logger.removeHandler(handler)
                handler.close()
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024**2, backupCount=3, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
            file_handler.addFilter(RedactingFilter())
            logger.addHandler(file_handler)
        except OSError as exc:
            # A missing drive must never stop the application from starting.
            logger.warning("Could not open the log file on the drive: %s", exc.__class__.__name__)

    return logger


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def describe(text: str) -> str:
    """Describe user content without reproducing it."""
    return f"<{len(text)} chars>"
