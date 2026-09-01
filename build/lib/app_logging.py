"""Small, best-effort application logging facade.

The module deliberately exposes no handlers or ``LogRecord`` objects to the
rest of the application.  Logging failures are swallowed so diagnostics can
never turn a drawing operation into a failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import re
import secrets
import sys
import threading
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app_info import get_version

_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 5
_MAX_TRACEBACK = 32 * 1024
_ALLOWED_FIELDS = frozenset({"operation_id", "duration_ms", "error_code", "path_hash"})
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s\"']+|/(?:[^\s\"']+/)+[^\s\"']+)")
_SECRET_RE = re.compile(
    r"(?i)\b(?:password|passwd|token|secret|api[_-]?key|authorization)\b\s*[:=]\s*[^\s,;]+"
)

_logger = logging.getLogger("drawsvg.app")
_logger.setLevel(logging.INFO)
_logger.propagate = False
_state_lock = threading.RLock()
_handler: logging.Handler | None = None
_session_id: str | None = None
_salt = secrets.token_bytes(32)
_hook_guard = threading.local()


def _log_directory() -> Path:
    override = os.environ.get("DRAWSVG_LOG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "DrawSVG" / "logs"


def _redact(value: str) -> str:
    value = _SECRET_RE.sub(lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=<redacted>", value)
    return _PATH_RE.sub("<path>", value)


def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _ALLOWED_FIELDS:
        if key not in fields:
            continue
        value = fields[key]
        if key == "duration_ms":
            try:
                value = max(0, float(value))
            except (TypeError, ValueError):
                continue
        elif not isinstance(value, (str, int, float, bool)):
            continue
        result[key] = _redact(str(value)) if isinstance(value, str) else value
    return result


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "event": getattr(record, "event", "internal.invariant"),
            "message": _redact(record.getMessage()),
            "session_id": _session_id or "unknown",
            "component": getattr(record, "component", "internal"),
            "app_version": get_version(),
        }
        payload.update(_safe_fields(getattr(record, "fields", {})))
        for key in ("exception_type", "traceback"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = _redact(str(value))[:_MAX_TRACEBACK]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _ensure_handler() -> None:
    global _handler
    if _handler is not None:
        return
    try:
        directory = _log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            directory / "app.log", maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(_JsonFormatter())
        _logger.addHandler(handler)
        _handler = handler
    except Exception:  # noqa: BLE001 - diagnostics must never affect the editor
        # Logging is explicitly best effort.  Keep a NullHandler so retries do
        # not repeatedly attempt a broken filesystem operation.
        _handler = logging.NullHandler()
        _logger.addHandler(_handler)


def start_session() -> str:
    """Start a process session and emit its lifecycle event."""
    global _session_id
    with _state_lock:
        _session_id = uuid.uuid4().hex
        _ensure_handler()
    log_event("INFO", "app.startup", component="startup", message="Application started")
    return _session_id


def log_event(level: str, event: str, *, component: str, message: str, operation_id: str | None = None, **fields: Any) -> None:
    """Write one structured event without allowing logging to escape."""
    try:
        with _state_lock:
            _ensure_handler()
            numeric_level = getattr(logging, str(level).upper(), logging.INFO)
            extras = _safe_fields({**fields, **({"operation_id": operation_id} if operation_id else {})})
            extra = {"event": event, "component": component, "fields": extras}
            for key in ("exception_type", "traceback"):
                if key in fields and isinstance(fields[key], str):
                    extra[key] = _redact(fields[key])[:_MAX_TRACEBACK]
            _logger.log(numeric_level, _redact(message), extra=extra)
    except Exception:  # noqa: BLE001 - diagnostics must never affect the editor
        return


def log_exception(event: str, exc: BaseException, *, component: str, operation_id: str | None = None, **fields: Any) -> None:
    """Log a controlled exception with bounded, redacted diagnostic data."""
    try:
        details = {**fields, "exception_type": type(exc).__name__}
        details["traceback"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[:_MAX_TRACEBACK]
        log_event("ERROR", event, component=component, message="Operation failed", operation_id=operation_id, **details)
    except Exception:  # noqa: BLE001 - diagnostics must never affect the editor
        return


def shutdown_logging() -> None:
    """Emit shutdown and close the file handler, best effort."""
    global _handler
    try:
        log_event("INFO", "app.shutdown", component="startup", message="Application stopped")
        with _state_lock:
            if _handler is not None:
                _handler.close()
                _logger.removeHandler(_handler)
                _handler = None
    except Exception:  # noqa: BLE001 - diagnostics must never affect the editor
        return


def install_excepthook() -> Callable[[], None]:
    """Install a hook that logs once, then delegates to the prior hook."""
    previous = sys.excepthook
    active = True

    def hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        if getattr(_hook_guard, "active", False):
            return previous(exc_type, exc, tb)
        _hook_guard.active = True
        try:
            exc.__traceback__ = tb
            log_exception("app.exception", exc, component="startup")
        finally:
            _hook_guard.active = False
        previous(exc_type, exc, tb)

    sys.excepthook = hook

    def restore() -> None:
        nonlocal active
        if active and sys.excepthook is hook:
            sys.excepthook = previous
        active = False

    return restore


def hash_path(path: str) -> str:
    """Return a process-local correlation hash for an approved path value."""
    return hashlib.sha256(_salt + path.encode("utf-8", errors="replace")).hexdigest()[:16]
