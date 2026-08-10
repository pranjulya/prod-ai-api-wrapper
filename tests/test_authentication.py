import logging
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


pytestmark = pytest.mark.filterwarnings(
    "ignore:Using `httpx` with `starlette.testclient` is deprecated"
)


def test_missing_bearer_key_returns_correlated_error():
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]


@pytest.mark.parametrize("authorization", ["Basic test-wrapper-key", "Bearer wrong-key"])
def test_invalid_bearer_key_is_rejected(authorization):
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"Authorization": authorization})

    assert response.status_code == 401


def test_non_ascii_bearer_key_is_rejected():
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        response = client.get("/health/live", headers={"Authorization": b"Bearer caf\xc3\xa9"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


def test_valid_client_correlation_id_is_returned():
    headers = {
        "Authorization": "Bearer test-wrapper-key",
        "X-Correlation-ID": "client.request-1",
    }
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers=headers)

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "client.request-1"


def test_missing_correlation_id_is_a_uuid4():
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"Authorization": "Bearer test-wrapper-key"})

    assert response.status_code == 200
    assert uuid.UUID(response.headers["X-Correlation-ID"]).version == 4


def test_malformed_correlation_id_returns_generated_correlated_error():
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"X-Correlation-ID": "bad id"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_correlation_id"
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]
    assert uuid.UUID(response.headers["X-Correlation-ID"]).version == 4


def test_downstream_exception_returns_correlated_error():
    app = create_app()

    @app.get("/__review_boom")
    async def review_boom():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__review_boom", headers={"Authorization": "Bearer test-wrapper-key"})

    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == response.json()["error"]["correlation_id"]


def test_framework_errors_are_correlated_standard_errors():
    app = create_app()

    @app.get("/__review_validation/{value}")
    async def review_validation(value: int):
        return {"value": value}

    with TestClient(app) as client:
        responses = [
            client.get("/health/missing", headers={"Authorization": "Bearer test-wrapper-key"}),
            client.post("/health/live", headers={"Authorization": "Bearer test-wrapper-key"}),
            client.get("/__review_validation/nope", headers={"Authorization": "Bearer test-wrapper-key"}),
            client.post("/webhooks/openai"),
        ]

    assert [response.status_code for response in responses] == [404, 405, 422, 404]
    assert responses[1].headers["Allow"] == "GET"
    for response in responses:
        body = response.json()
        assert set(body) == {"error"}
        assert response.headers["X-Correlation-ID"] == body["error"]["correlation_id"]


def test_webhook_path_is_exempt_from_wrapper_authentication():
    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai")

    assert response.status_code == 404
    assert response.headers["X-Correlation-ID"]


def test_correlation_log_excludes_credentials(caplog):
    caplog.set_level(logging.INFO)
    headers = {
        "Authorization": "Bearer test-wrapper-key",
        "X-Correlation-ID": "client.request-1",
    }
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers=headers)

    assert response.status_code == 200
    assert re.search(r"client\.request-1.*200", caplog.text)
    assert "test-wrapper-key" not in caplog.text
    assert "Authorization" not in caplog.text


def test_downstream_exception_log_excludes_exception_details(caplog):
    caplog.set_level(logging.INFO)
    app = create_app()

    @app.get("/__review_secret_boom")
    async def review_secret_boom():
        raise RuntimeError("Bearer test-wrapper-key")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__review_secret_boom", headers={"Authorization": "Bearer test-wrapper-key"})

    assert response.status_code == 500
    assert re.search(r"request failed correlation_id=.* exception_type=RuntimeError", caplog.text)
    assert "test-wrapper-key" not in caplog.text
