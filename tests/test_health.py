import pytest
from fastapi.testclient import TestClient

from app.main import create_app

pytestmark = pytest.mark.filterwarnings(
    "ignore:Using `httpx` with `starlette.testclient` is deprecated"
)


def test_liveness_reports_a_running_process():
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_openapi_includes_the_liveness_route():
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health/live" in response.json()["paths"]


def test_invalid_log_level_prevents_application_startup(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "loud")

    with pytest.raises(ValueError, match="LOG_LEVEL"):
        with TestClient(create_app()):
            pass
