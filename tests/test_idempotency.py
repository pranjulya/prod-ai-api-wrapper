from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import create_app


class FakeResponses:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(id="resp-id", status="completed", model=kwargs["model"], output_text="ok", usage=None)


class FakeOpenAI:
    def __init__(self):
        self.responses = FakeResponses()

    async def close(self):
        pass


def headers(key="idem-key"):
    return {"Authorization": "Bearer test-wrapper-key", "Idempotency-Key": key}


def test_same_key_replays_without_second_provider_call(monkeypatch):
    client = FakeOpenAI()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: client)
    with TestClient(create_app()) as http:
        first = http.post("/v1/responses", headers=headers(), json={"input": "Hi"})
        second = http.post("/v1/responses", headers=headers(), json={"input": "Hi"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.responses.calls == 1


def test_same_key_different_body_conflicts(monkeypatch):
    client = FakeOpenAI()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: client)
    with TestClient(create_app()) as http:
        http.post("/v1/responses", headers=headers(), json={"input": "Hi"})
        result = http.post("/v1/responses", headers=headers(), json={"input": "Different"})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "idempotency_key_reused"
    assert client.responses.calls == 1


def test_missing_key_is_rejected(monkeypatch):
    client = FakeOpenAI()
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: client)
    with TestClient(create_app()) as http:
        result = http.post("/v1/responses", headers={"Authorization": "Bearer test-wrapper-key"}, json={"input": "Hi"})
    assert result.status_code == 422
    assert client.responses.calls == 0
