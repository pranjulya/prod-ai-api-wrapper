import io
import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient

from app.logging import (
    JsonFormatter,
    bind_correlation_id,
    configure_logging,
    log_event,
    reset_correlation_id,
)
from app.main import create_app


def decode(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def event(records, name):
    return [record for record in records if record["event"] == name]


def test_application_event_is_json_and_whitelists_fields():
    stream = io.StringIO()
    logger = logging.getLogger("app.test.structured")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    token = bind_correlation_id("corr-1")
    try:
        log_event(
            logger,
            logging.INFO,
            "request_completed",
            method="GET",
            status_code=200,
            duration_ms=1.25,
            authorization="Bearer secret",
            body={"secret": True},
        )
    finally:
        reset_correlation_id(token)

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "request_completed"
    assert payload["level"] == "info"
    assert payload["logger"] == "app.test.structured"
    assert payload["correlation_id"] == "corr-1"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.25
    assert "authorization" not in payload
    assert "body" not in payload
    assert payload["timestamp"].endswith("Z")


def test_uvicorn_access_record_is_structured_without_query_string():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/health/live?token=secret", "1.1", 200),
        None,
    )
    payload = decode(record)
    assert payload == {
        "timestamp": payload["timestamp"],
        "level": "info",
        "event": "uvicorn_access",
        "logger": "uvicorn.access",
        "method": "GET",
        "route": "/health/live",
        "status_code": 200,
    }
    assert "secret" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("message", "args", "secret"),
    [
        ("Started %s", ("formatted-secret",), "formatted-secret"),
        (RuntimeError("exception-secret"), (), "exception-secret"),
        ("Lifespan startup failed: lifespan-secret", (), "lifespan-secret"),
    ],
)
def test_uvicorn_server_record_uses_static_safe_message(message, args, secret):
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        message,
        args,
        None,
    )
    payload = decode(record)
    assert payload["event"] == "uvicorn_server"
    assert payload["message"] == "Uvicorn server record."
    assert secret not in json.dumps(payload)


def test_third_party_record_drops_original_message_and_exception():
    record = logging.LogRecord(
        "httpx",
        logging.ERROR,
        __file__,
        1,
        "Bearer secret-in-message",
        (),
        RuntimeError,
    )
    payload = decode(record)
    assert payload["event"] == "third_party_log"
    assert payload["message"] == "Third-party log record."
    assert "secret-in-message" not in json.dumps(payload)


def test_third_party_record_with_event_attribute_is_still_redacted():
    record = logging.LogRecord(
        "httpx",
        logging.ERROR,
        __file__,
        1,
        "ignored",
        (),
        None,
    )
    record.event = "third-party-event-secret"
    record.duration_ms = float("nan")

    payload = decode(record)

    assert payload["event"] == "third_party_log"
    assert payload["message"] == "Third-party log record."
    assert "third-party-event-secret" not in json.dumps(payload, allow_nan=False)
    assert "duration_ms" not in payload


def test_application_event_omits_malformed_and_nonfinite_fields():
    stream = io.StringIO()
    logger = logging.getLogger("app.test.invalid-fields")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    log_event(
        logger,
        logging.INFO,
        "safe_event",
        status_code=object(),
        duration_ms=float("nan"),
    )

    payload = json.loads(stream.getvalue(), parse_constant=lambda value: pytest.fail(value))
    assert payload["event"] == "safe_event"
    assert "status_code" not in payload
    assert "duration_ms" not in payload


def test_configuration_keeps_non_production_capture_handler_formatter():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = logging.Formatter("capture:%(message)s")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        configure_logging("INFO")
        logging.getLogger("app.test.capture").info("hello")
    finally:
        root.removeHandler(handler)

    assert handler.formatter is formatter
    assert stream.getvalue().strip() == "capture:hello"


def test_configuration_reuses_one_console_handler_and_preserves_capture(monkeypatch):
    root = logging.getLogger()
    stderr_handler = logging.StreamHandler(sys.stderr)
    stdout_handler = logging.StreamHandler(sys.stdout)
    capture_stream = io.StringIO()
    capture_handler = logging.StreamHandler(capture_stream)
    capture_formatter = logging.Formatter("capture:%(message)s")
    capture_handler.setFormatter(capture_formatter)
    monkeypatch.setattr(root, "handlers", [stderr_handler, stdout_handler, capture_handler])
    monkeypatch.setattr(root, "level", root.level)

    configure_logging("INFO")

    console_handlers = [handler for handler in root.handlers if handler in {stderr_handler, stdout_handler}]
    assert len(console_handlers) == 1
    assert console_handlers[0].stream is sys.stdout
    assert getattr(console_handlers[0], "wrapper_json_handler", False)
    assert capture_handler in root.handlers
    assert capture_handler.formatter is capture_formatter
    logging.getLogger("app.test.capture-topology").info("hello")
    assert capture_stream.getvalue().strip() == "capture:hello"


def test_configuration_is_idempotent_and_applies_level():
    configure_logging("DEBUG")
    configure_logging("DEBUG")
    root = logging.getLogger()
    managed = [handler for handler in root.handlers if getattr(handler, "wrapper_json_handler", False)]
    assert len(managed) == 1
    assert managed[0].stream is sys.stdout
    assert root.level == logging.DEBUG
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert logger.level == logging.DEBUG
        assert logger.handlers == []
        assert logger.propagate is True


@pytest.mark.parametrize("invalid_event", [object(), float("nan")])
def test_malformed_application_event_falls_back_to_strict_valid_json(invalid_event):
    stream = io.StringIO()
    logger = logging.getLogger("app.test.malformed")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    log_event(logger, logging.INFO, invalid_event)

    payload = json.loads(stream.getvalue(), parse_constant=lambda value: pytest.fail(value))
    assert payload["event"] == "logging_error"
    assert set(payload) == {"timestamp", "level", "event", "logger"}


def test_request_lifecycle_is_correlated_and_uses_route_template(captured_events):
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live",
            headers={
                "Authorization": "Bearer test-wrapper-key",
                "X-Correlation-ID": "trace-14",
            },
        )

    started = event(captured_events, "request_started")[-1]
    completed = event(captured_events, "request_completed")[-1]
    assert response.status_code == 200
    assert started["correlation_id"] == completed["correlation_id"] == "trace-14"
    assert completed["method"] == "GET"
    assert completed["route"] == "/health/live"
    assert completed["status_code"] == 200
    assert completed["duration_ms"] >= 0


def test_invalid_correlation_completion_is_categorized(captured_events):
    with TestClient(create_app()) as client:
        response = client.get(
            "/health/live",
            headers={
                "Authorization": "Bearer test-wrapper-key",
                "X-Correlation-ID": "invalid value",
            },
        )

    completed = event(captured_events, "request_completed")[-1]
    assert response.status_code == 400
    assert completed["status_code"] == 400
    assert completed["error_category"] == "validation"


def test_prefixed_dynamic_route_uses_full_route_template(captured_events):
    with TestClient(create_app()) as client:
        response = client.get(
            "/v1/responses/not-a-job-id",
            headers={"Authorization": "Bearer test-wrapper-key"},
        )

    completed = event(captured_events, "request_completed")[-1]
    assert response.status_code == 404
    assert completed["route"] == "/v1/responses/{job_id}"
