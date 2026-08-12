from fastapi.testclient import TestClient

from app.main import create_app


class FakeOpenAI:
    def __init__(self, error=None):
        self.error = error
        self.closed = False

    async def close(self):
        self.closed = True
        if self.error:
            raise self.error


def test_openai_client_created_and_closed(monkeypatch):
    fake = FakeOpenAI()
    captured = {}

    def create(settings):
        captured["settings"] = settings
        return fake

    monkeypatch.setattr("app.main.create_openai_client", create)

    with TestClient(create_app()):
        pass

    assert captured["settings"].openai_api_key == "test-openai-key"
    assert captured["settings"].openai_timeout_seconds == 30
    assert fake.closed


def test_openai_close_does_not_skip_redis_close(monkeypatch):
    fake = FakeOpenAI(RuntimeError("openai close failed"))
    redis = type("FakeRedis", (), {"closed": False})()

    async def close_redis():
        redis.closed = True

    redis.aclose = close_redis
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: fake)
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)

    try:
        with TestClient(create_app()):
            pass
    except RuntimeError:
        pass

    assert fake.closed
    assert redis.closed
