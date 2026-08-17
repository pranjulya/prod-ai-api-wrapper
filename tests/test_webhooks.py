import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APITimeoutError, InvalidWebhookSignatureError
from redis.exceptions import ConnectionError

from app.main import create_app
from app.schemas.jobs import JobRecord, JobStatus
from app.services.jobs import job_key, response_job_key
from app.api.webhooks import MAX_WEBHOOK_BODY_BYTES
from app.services.webhooks import event_key
from conftest import FakeRedis


JOB_ID = "job_00000000-0000-4000-8000-000000000000"
SIGNED_HEADERS = {
    "webhook-signature": "v1,test-signature",
    "webhook-timestamp": "1755000000",
    "webhook-id": "wh_test",
}


class FakeWebhooks:
    def __init__(self, event=None, error=None):
        self.event = event
        self.error = error
        self.calls = []

    def unwrap(self, body, headers):
        self.calls.append((body, headers))
        if self.error:
            raise self.error
        return self.event


class FakeResponses:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.retrieve_calls = []

    async def retrieve(self, response_id):
        self.retrieve_calls.append(response_id)
        if self.error:
            raise self.error
        return self.result


class FakeOpenAI:
    def __init__(self, event=None, result=None, webhook_error=None, response_error=None):
        self.webhooks = FakeWebhooks(event, webhook_error)
        self.responses = FakeResponses(result, response_error)

    async def close(self):
        pass


def event(event_id="evt_1", event_type="response.completed", response_id="resp_1"):
    return SimpleNamespace(
        id=event_id,
        object="event",
        type=event_type,
        created_at=1_755_000_000,
        data=SimpleNamespace(id=response_id),
    )


def job(status=JobStatus.IN_PROGRESS):
    now = datetime.now(timezone.utc)
    return JobRecord(
        id=JOB_ID,
        status=status,
        openai_response_id="resp_1",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        status_url=f"/v1/responses/{JOB_ID}",
        correlation_id="background-correlation",
    )


def install(monkeypatch, redis, openai):
    monkeypatch.setattr("app.main.create_redis", lambda url: redis)
    monkeypatch.setattr("app.main.create_openai_client", lambda settings: openai)


def send(client, body=b"raw"):
    return client.post("/webhooks/openai", content=body, headers=SIGNED_HEADERS)


def seed_job(redis, record=None):
    record = record or job()
    redis.values[job_key(record.id)] = record.model_dump_json()
    redis.values[response_job_key("resp_1")] = record.id
    return record


def completed_response():
    usage = SimpleNamespace(input_tokens=5, output_tokens=3, total_tokens=8)
    return SimpleNamespace(
        id="resp_1",
        _request_id="req_webhook",
        status="completed",
        model="gpt-5-mini",
        output_text="done",
        usage=usage,
    )


def test_invalid_signature_is_rejected_before_state_access(monkeypatch):
    redis = FakeRedis()
    openai = FakeOpenAI(webhook_error=InvalidWebhookSignatureError("bad"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/openai",
            content=b'{"signed":true}',
            headers={**SIGNED_HEADERS, "X-Correlation-ID": "webhook-correlation"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_signature"
    assert response.json()["error"]["correlation_id"] == "webhook-correlation"
    assert redis.values == {}
    assert openai.responses.retrieve_calls == []


def test_invalid_signature_emits_rejected_event(monkeypatch, captured_events):
    redis = FakeRedis()
    openai = FakeOpenAI(webhook_error=InvalidWebhookSignatureError("secret-exception-text"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post(
            "/webhooks/openai",
            content=b'{"secret-body":true}',
            headers=SIGNED_HEADERS,
        )

    rejected = [record for record in captured_events if record["event"] == "webhook_rejected"][-1]
    assert response.status_code == 401
    assert rejected["status_code"] == 401
    assert rejected["error_category"] == "webhook_signature"
    assert "secret-exception-text" not in json.dumps(captured_events)
    assert "secret-body" not in json.dumps(captured_events)


def test_missing_signature_is_rejected_by_the_real_sdk():
    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=b"{}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_webhook_signature"


@pytest.mark.parametrize(
    "content",
    [
        b"x" * (MAX_WEBHOOK_BODY_BYTES + 1),
        iter((b"x" * (MAX_WEBHOOK_BODY_BYTES // 2), b"y" * (MAX_WEBHOOK_BODY_BYTES // 2 + 1))),
    ],
)
def test_oversized_webhook_body_is_rejected_before_verification(
    monkeypatch, captured_events, content
):
    redis = FakeRedis()
    openai = FakeOpenAI(event=event(event_type="batch.completed"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = client.post("/webhooks/openai", content=content, headers=SIGNED_HEADERS)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert openai.webhooks.calls == []
    assert redis.values == {}
    rejected = [record for record in captured_events if record["event"] == "webhook_rejected"][-1]
    assert rejected["status_code"] == 413
    assert rejected["error_category"] == "request_too_large"


def test_verified_webhook_emits_safe_type(monkeypatch, captured_events):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    verified = [record for record in captured_events if record["event"] == "webhook_verified"][-1]
    assert response.status_code == 200
    assert verified["webhook_type"] == "response.completed"
    serialized = json.dumps(captured_events)
    assert "test-signature" not in serialized
    assert "evt_1" not in serialized
    assert "resp_1" not in serialized
    assert "done" not in serialized


def test_verified_unsupported_event_is_acknowledged_without_state_change(monkeypatch):
    redis = FakeRedis()
    openai = FakeOpenAI(event=event(event_type="batch.completed"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client, b"raw-body")

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert openai.webhooks.calls[0][0] == b"raw-body"
    assert openai.webhooks.calls[0][1]["webhook-id"] == "wh_test"
    assert redis.values == {}
    assert redis.pipeline_calls == 0


def test_completed_event_updates_polling_result_once(monkeypatch, captured_events):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        first = send(client)
        second = send(client)
        polled = client.get(
            f"/v1/responses/{JOB_ID}",
            headers={"Authorization": "Bearer test-wrapper-key"},
        )

    assert first.status_code == second.status_code == 200
    assert openai.responses.retrieve_calls == ["resp_1"]
    assert polled.json()["status"] == "completed"
    assert polled.json()["model"] == "gpt-5-mini"
    assert polled.json()["output_text"] == "done"
    assert polled.json()["usage"]["total_tokens"] == 8
    completed = [record for record in captured_events if record["event"] == "job_completed"]
    assert len(completed) == 1
    assert completed[0]["job_id"] == JOB_ID
    assert completed[0]["correlation_id"] == "background-correlation"
    assert completed[0]["openai_request_id"] == "req_webhook"
    started = [record for record in captured_events if record["event"] == "openai_request_started"]
    assert started[-1]["operation"] == "retrieve"
    request_completed = [
        record
        for record in captured_events
        if record["event"] == "request_completed" and record.get("openai_request_id")
    ]
    assert request_completed[0]["openai_request_id"] == "req_webhook"


def test_completed_event_passes_bounded_retry_operation_name(monkeypatch):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)
    calls = []

    async def capture_retry(operation, *, operation_name, max_retries=2, sleep=None, random_value=None):
        calls.append(operation_name)
        return await operation()

    monkeypatch.setattr("app.api.webhooks.retry_async", capture_retry)

    with TestClient(create_app()) as client:
        response = send(client)

    assert response.status_code == 200
    assert response.json() == {"received": True}
    assert calls == ["retrieve"]
    assert openai.responses.retrieve_calls == ["resp_1"]


def test_unknown_response_is_retryable_and_released(monkeypatch):
    redis = FakeRedis()
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        first = send(client)
        seed_job(redis)
        second = send(client)

    assert first.status_code == 503
    assert second.status_code == 200


def test_later_terminal_event_does_not_overwrite_completed_job(monkeypatch, captured_events):
    redis = FakeRedis()
    seed_job(redis, job(JobStatus.COMPLETED).model_copy(update={"output_text": "kept"}))
    openai = FakeOpenAI(event=event(event_id="evt_late", event_type="response.failed"))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    stored = JobRecord.model_validate_json(redis.values[job_key(JOB_ID)])
    assert response.status_code == 200
    assert stored.status is JobStatus.COMPLETED
    assert stored.output_text == "kept"
    assert openai.responses.retrieve_calls == []
    assert not [record for record in captured_events if record["event"] == "job_completed"]


def test_completed_event_losing_terminal_race_emits_no_completion(monkeypatch, captured_events):
    class TerminalRaceRedis(FakeRedis):
        async def eval(self, script, numkeys, *args):
            if script.startswith("-- finalize-webhook-event"):
                stored_job_key = args[1]
                self.values[stored_job_key] = job(JobStatus.FAILED).model_dump_json()
            return await super().eval(script, numkeys, *args)

    redis = TerminalRaceRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    stored = JobRecord.model_validate_json(redis.values[job_key(JOB_ID)])
    assert response.status_code == 200
    assert stored.status is JobStatus.FAILED
    assert not [record for record in captured_events if record["event"] == "job_completed"]


@pytest.mark.parametrize(
    ("event_type", "expected_status"),
    [
        ("response.failed", JobStatus.FAILED),
        ("response.cancelled", JobStatus.CANCELLED),
        ("response.incomplete", JobStatus.INCOMPLETE),
    ],
)
def test_non_completed_terminal_events_do_not_retrieve(monkeypatch, event_type, expected_status):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(event_type=event_type))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    stored = JobRecord.model_validate_json(redis.values[job_key(JOB_ID)])
    assert response.status_code == 200
    assert stored.status is expected_status
    assert openai.responses.retrieve_calls == []


def test_concurrent_owner_returns_retryable_503(monkeypatch):
    redis = FakeRedis()
    redis.values[event_key("evt_1")] = "processing"
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    assert response.status_code == 503
    assert openai.responses.retrieve_calls == []


def test_redis_failure_returns_retryable_503(monkeypatch, captured_events):
    class ErrorRedis(FakeRedis):
        async def set(self, key, value, nx=False, ex=None):
            raise ConnectionError("redis-secret")

    redis = ErrorRedis()
    openai = FakeOpenAI(event=event(), result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    failed = [record for record in captured_events if record["event"] == "request_failed"][-1]
    assert failed["operation"] == "webhook"
    assert failed["status_code"] == 503
    assert failed["error_category"] == "redis"
    assert "redis-secret" not in json.dumps(captured_events)


def test_retrieval_timeout_returns_504_and_releases_claim(monkeypatch):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), response_error=APITimeoutError(request=None))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert event_key("evt_1") not in redis.values


def test_transient_retrieval_exhaustion_returns_503_and_releases_claim(monkeypatch):
    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), response_error=APIConnectionError(request=None))
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert event_key("evt_1") not in redis.values


def test_transient_retrieval_is_retried_then_completed(monkeypatch):
    class FlakyResponses(FakeResponses):
        async def retrieve(self, response_id):
            self.retrieve_calls.append(response_id)
            if len(self.retrieve_calls) == 1:
                raise APIConnectionError(request=None)
            return self.result

    redis = FakeRedis()
    seed_job(redis)
    openai = FakeOpenAI(event=event(), result=completed_response())
    openai.responses = FlakyResponses(result=completed_response())
    install(monkeypatch, redis, openai)

    with TestClient(create_app()) as client:
        response = send(client)

    assert response.status_code == 200
    assert openai.responses.retrieve_calls == ["resp_1", "resp_1"]
