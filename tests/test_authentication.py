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
