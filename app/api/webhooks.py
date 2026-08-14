from fastapi import APIRouter, HTTPException, Request
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InvalidWebhookSignatureError,
    RateLimitError,
)
from redis.exceptions import RedisError

from app.errors import error_response
from app.schemas.jobs import JobStatus
from app.services.jobs import get_job, get_job_id_by_response_id
from app.services.responses import normalize_response
from app.services.retry import retry_async
from app.services.webhooks import (
    EventClaim,
    claim_event,
    finalize_event,
    mark_processed,
    processing_ttl,
    release_event,
)


router = APIRouter()
SIGNATURE_HEADERS = ("webhook-signature", "webhook-timestamp", "webhook-id")
EVENT_STATUSES = {
    "response.completed": JobStatus.COMPLETED,
    "response.failed": JobStatus.FAILED,
    "response.cancelled": JobStatus.CANCELLED,
    "response.incomplete": JobStatus.INCOMPLETE,
}
TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
    JobStatus.INCOMPLETE,
    JobStatus.EXPIRED,
}


async def _release_safely(redis, event_id: str) -> None:
    try:
        await release_event(redis, event_id)
    except RedisError:
        pass


def _invalid_signature(correlation_id: str):
    return error_response(
        401,
        "invalid_webhook_signature",
        "Webhook signature verification failed.",
        correlation_id,
    )


@router.post("/openai")
async def receive_openai_webhook(request: Request):
    raw_body = await request.body()
    if not all(request.headers.get(name) for name in SIGNATURE_HEADERS):
        return _invalid_signature(request.state.correlation_id)
    try:
        event = request.app.state.openai.webhooks.unwrap(raw_body, request.headers)
    except InvalidWebhookSignatureError:
        return _invalid_signature(request.state.correlation_id)

    target_status = EVENT_STATUSES.get(event.type)
    if target_status is None:
        return {"received": True}

    redis = request.app.state.redis
    claimed = False
    try:
        claim = await claim_event(
            redis,
            event.id,
            processing_ttl(request.app.state.settings.openai_timeout_seconds),
        )
        if claim is EventClaim.PROCESSED:
            return {"received": True}
        if claim is EventClaim.PROCESSING:
            raise HTTPException(status_code=503)
        claimed = True

        job_id = await get_job_id_by_response_id(redis, event.data.id)
        record = None if job_id is None else await get_job(redis, job_id)
        if record is None:
            await release_event(redis, event.id)
            claimed = False
            raise HTTPException(status_code=503)

        if record.status in TERMINAL_STATUSES:
            await mark_processed(redis, event.id)
            claimed = False
            return {"received": True}

        if target_status is JobStatus.COMPLETED:
            provider = await retry_async(lambda: request.app.state.openai.responses.retrieve(event.data.id))
            if getattr(provider, "status", None) != "completed":
                await release_event(redis, event.id)
                claimed = False
                raise HTTPException(status_code=503)
            normalized = normalize_response(provider, record.correlation_id)
            record = record.model_copy(
                update={
                    "status": JobStatus.COMPLETED,
                    "model": normalized.model,
                    "output_text": normalized.output_text,
                    "usage": normalized.usage,
                }
            )
        else:
            record = record.model_copy(update={"status": target_status})

        await finalize_event(redis, event.id, record)
        claimed = False
        return {"received": True}
    except RedisError:
        if claimed:
            await _release_safely(redis, event.id)
        raise HTTPException(status_code=503) from None
    except APITimeoutError:
        if claimed:
            await _release_safely(redis, event.id)
        raise HTTPException(status_code=504) from None
    except (APIConnectionError, AuthenticationError, RateLimitError):
        if claimed:
            await _release_safely(redis, event.id)
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        if claimed:
            await _release_safely(redis, event.id)
        if error.status_code >= 500:
            raise HTTPException(status_code=503) from None
        raise
    except Exception:
        if claimed:
            await _release_safely(redis, event.id)
        raise
