from concurrent.futures import ThreadPoolExecutor

import redis
from fastapi.testclient import TestClient

from app.main import create_app
from conftest import FakeRedis


def auth_headers():
    return {"Authorization": "Bearer test-wrapper-key"}


def event(records, name):
    return [record for record in records if record["event"] == name]


def app_with_test_route():
    app = create_app()

    @app.get("/test-route")
    async def test_route():
        return {"ok": True}

    return app


def test_health_paths_bypass_rate_limit_counter(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(app_with_test_route()) as client:
        assert client.get("/health/live", headers=auth_headers()).status_code == 200
        assert client.get("/health/ready", headers=auth_headers()).status_code == 200

    assert fake.pipeline_calls == 0


def test_invalid_authentication_is_rejected_before_rate_limit(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(app_with_test_route()) as client:
        response = client.get("/test-route")

    assert response.status_code == 401
    assert fake.pipeline_calls == 0


def test_allowed_request_reaches_route(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(app_with_test_route()) as client:
        response = client.get("/test-route", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_rejected_request_has_retry_after_and_stable_error(monkeypatch, captured_events):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(app_with_test_route()) as client:
        assert client.get("/test-route", headers=auth_headers()).status_code == 200
        response = client.get("/test-route", headers=auth_headers())

    rejected = event(captured_events, "rate_limit_rejected")[-1]
    assert response.status_code == 429
    assert response.headers["Retry-After"].isdigit()
    assert response.json()["error"]["code"] == "rate_limit_exceeded"
    assert rejected["status_code"] == 429
    assert rejected["retry_after"] == int(response.headers["Retry-After"])
    assert rejected["error_category"] == "rate_limit"


def test_redis_failure_returns_upstream_unavailable(monkeypatch, captured_events):
    fake = FakeRedis(redis.exceptions.ConnectionError("offline"))
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(app_with_test_route()) as client:
        response = client.get("/test-route", headers=auth_headers())

    failed = event(captured_events, "request_failed")[-1]
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert failed["status_code"] == 503
    assert failed["error_category"] == "redis"


def test_concurrent_requests_share_one_counter(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(app_with_test_route()) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: client.get("/test-route", headers=auth_headers()).status_code, range(2)))

    assert sorted(statuses) == [200, 429]
