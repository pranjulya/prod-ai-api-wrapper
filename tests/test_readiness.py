import redis
from fastapi.testclient import TestClient

from app.main import create_app


class FakeRedis:
    def __init__(self, ping_error=None):
        self.ping_error = ping_error
        self.closed = False

    async def ping(self):
        if self.ping_error:
            raise self.ping_error
        return True

    async def aclose(self):
        self.closed = True


def auth_headers():
    return {"Authorization": "Bearer test-wrapper-key"}


def test_readiness_reports_ready_and_closes_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(create_app()) as client:
        response = client.get("/health/ready", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert fake.closed


def test_readiness_fails_but_liveness_stays_live(monkeypatch):
    fake = FakeRedis(redis.exceptions.ConnectionError("offline"))
    monkeypatch.setattr("app.main.create_redis", lambda url: fake)

    with TestClient(create_app()) as client:
        ready = client.get("/health/ready", headers=auth_headers())
        live = client.get("/health/live", headers=auth_headers())

    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "upstream_unavailable"
    assert live.status_code == 200
