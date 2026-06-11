"""Logging bootstrap: pythonw-safe std streams and rotating file logs.

Call order matters (see docs/ARCHITECTURE.md): :func:`guard_std_streams` must
run first thing in the entry point — under ``pythonw.exe`` ``sys.stdout`` and
``sys.stderr`` are ``None`` and anything that writes to them (including
logging's last-resort handler) would raise (cpython #122633 / #107792).
:func:`setup_logging` is then safe to call before ``paths.ensure_dirs()``;
it creates the log directory itself.

Pure module — zero Qt imports.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from lyrics_overlay import paths

LOG_FILE_NAME = "lyricoverlay.log"

_MAX_BYTES = 1_000_000   # 1 MB per file
_BACKUP_COUNT = 3        # lyricoverlay.log + .1/.2/.3
_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def guard_std_streams() -> None:
    """Replace ``None`` std streams with devnull writers (pythonw guard).

    Under ``pythonw.exe`` there is no console, so ``sys.stdout``/``sys.stderr``
    are ``None``; any later write — third-party prints, tracebacks, logging's
    last-resort handler — would raise ``AttributeError``. Must be called
    BEFORE any code path that might write to the std streams. Idempotent;
    no-op when real streams exist. The devnull handles intentionally live for
    the rest of the process.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _stderr_is_tty() -> bool:
    """True only when ``sys.stderr`` is a real interactive terminal stream."""
    stream = sys.stderr
    if stream is None:
        return False
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        # ValueError: operations on a closed/detached stream.
        return False


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging: rotating file handler, optional tty echo.

    - ``RotatingFileHandler`` at ``LOG_DIR/lyricoverlay.log``, 1 MB x 3
      backups, utf-8. The log directory is created here because this runs
      before ``paths.ensure_dirs()``.
    - A ``StreamHandler`` is added only when ``sys.stderr`` is a real tty
      (developer console runs) — never under pythonw, even after
      :func:`guard_std_streams` swapped in devnull.
    - Unknown ``level`` strings fall back to INFO.
    - Idempotent: repeat calls only adjust the root level, never duplicate
      handlers.
    """
    global _configured

    resolved = logging.getLevelNamesMapping().get(str(level).strip().upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(resolved)

    if _configured:
        return

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    file_error: OSError | None = None
    try:
        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            paths.LOG_DIR / LOG_FILE_NAME,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        # Log dir unwritable: keep running; echo to stderr if we have one.
        file_error = exc

    if _stderr_is_tty():
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    logging.captureWarnings(True)
    _configured = True

    log = logging.getLogger(__name__)
    if file_error is not None:
        log.warning("Could not open log file in %s: %s", paths.LOG_DIR, file_error)
    log.debug("Logging configured at level %s", logging.getLevelName(resolved))
