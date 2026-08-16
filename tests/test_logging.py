import io
import json
import logging
import sys

from fastapi.testclient import TestClient

from app.main import create_app
from app.logging import (
    JsonFormatter,
    bind_correlation_id,
    configure_logging,
    log_event,
    reset_correlation_id,
)


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


def test_uvicorn_server_record_keeps_only_the_rendered_message():
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        "Started %s",
        ("server",),
        None,
    )
    payload = decode(record)
    assert payload["event"] == "uvicorn_server"
    assert payload["message"] == "Started server"


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


def test_malformed_record_falls_back_to_valid_json():
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "ignored", (), None)
    record.event = object()
    payload = decode(record)
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
