import contextvars
import json
import logging
import math
import sys
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit


ALLOWED_FIELDS = frozenset(
    {
        "correlation_id",
        "method",
        "route",
        "status_code",
        "duration_ms",
        "job_id",
        "retry_count",
        "openai_request_id",
        "error_category",
        "operation",
        "retry_after",
        "webhook_type",
    }
)
_correlation_id = contextvars.ContextVar("correlation_id", default=None)
_MISSING = object()


def _safe(value):
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return _MISSING
    if isinstance(value, bool | str | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return _MISSING


def _timestamp(created: float | None = None) -> str:
    value = (
        datetime.fromtimestamp(created, timezone.utc)
        if isinstance(created, int | float)
        else datetime.now(timezone.utc)
    )
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = {
                "timestamp": _timestamp(record.created),
                "level": record.levelname.lower(),
                "event": getattr(record, "event", "third_party_log"),
                "logger": record.name,
            }
            if record.name == "uvicorn.access":
                _, method, target, _, status_code = record.args
                payload.update(
                    event="uvicorn_access",
                    method=str(method),
                    route=urlsplit(str(target)).path,
                    status_code=int(status_code),
                )
            elif record.name in {"uvicorn", "uvicorn.error"}:
                payload.update(event="uvicorn_server", message=record.getMessage())
            elif record.name == "app.middleware.correlation":
                payload.update(event="app_log", message=record.getMessage())
            elif hasattr(record, "event"):
                for field in ALLOWED_FIELDS:
                    value = _safe(getattr(record, field, None))
                    if value is not _MISSING:
                        payload[field] = value
            else:
                payload["message"] = "Third-party log record."
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return json.dumps(
                {
                    "timestamp": _timestamp(),
                    "level": "error",
                    "event": "logging_error",
                    "logger": "logging",
                },
                separators=(",", ":"),
            )


def bind_correlation_id(value: str):
    return _correlation_id.set(value)


def reset_correlation_id(token) -> None:
    _correlation_id.reset(token)


def log_event(logger: logging.Logger, level: int, event: str, **fields: object) -> None:
    extras = {"event": event}
    correlation_id = fields.pop("correlation_id", None) or _correlation_id.get()
    if correlation_id is not None:
        fields["correlation_id"] = correlation_id
    for name, raw in fields.items():
        if name in ALLOWED_FIELDS:
            value = _safe(raw)
            if value is not _MISSING:
                extras[name] = value
    try:
        logger.log(level, event, extra=extras)
    except Exception:
        return


def configure_logging(level: str) -> None:
    numeric_level = logging.getLevelNamesMapping().get(str(level).strip().upper(), logging.INFO)
    formatter = JsonFormatter()
    root = logging.getLogger()
    root.setLevel(numeric_level)
    for handler in root.handlers:
        handler.setFormatter(formatter)
    managed = next(
        (handler for handler in root.handlers if getattr(handler, "wrapper_json_handler", False)),
        None,
    )
    if managed is None:
        managed = logging.StreamHandler(sys.stdout)
        managed.wrapper_json_handler = True
        root.addHandler(managed)
    managed.setLevel(numeric_level)
    managed.setFormatter(formatter)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(numeric_level)
        logger.propagate = True
