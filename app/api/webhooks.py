import logging
import secrets

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
from app.logging import log_event
from app.schemas.jobs import JobStatus
from app.services.job_reconciliation import TERMINAL_STATUSES, apply_job_transition
from app.services.jobs import get_job, get_job_id_by_response_id
from app.services.retry import openai_request_id, retry_async
from app.services.webhooks import (
    EventClaim,
    FinalizationResult,
    claim_event,
    finalize_event,
    mark_processed,
    processing_ttl,
    release_event,
)

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_WEBHOOK_BODY_BYTES = 1024 * 1024
SIGNATURE_HEADERS = ("webhook-signature", "webhook-timestamp", "webhook-id")
EVENT_STATUSES = {
    "response.completed": JobStatus.COMPLETED,
    "response.failed": JobStatus.FAILED,
    "response.cancelled": JobStatus.CANCELLED,
    "response.incomplete": JobStatus.INCOMPLETE,
}
async def _release_safely(redis, event_id: str, owner_token: str) -> None:
    try:
        await release_event(redis, event_id, owner_token)
    except RedisError:
        pass


def _invalid_signature(correlation_id: str):
    log_event(
        logger,
        logging.WARNING,
        "webhook_rejected",
        status_code=401,
        error_category="webhook_signature",
    )
    return error_response(
        401,
        "invalid_webhook_signature",
        "Webhook signature verification failed.",
        correlation_id,
    )


@router.post("/openai")
async def receive_openai_webhook(request: Request):
    if not all(request.headers.get(name) for name in SIGNATURE_HEADERS):
        return _invalid_signature(request.state.correlation_id)
    body_parts = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_WEBHOOK_BODY_BYTES:
            log_event(
                logger,
                logging.WARNING,
                "webhook_rejected",
                status_code=413,
                error_category="request_too_large",
            )
            return error_response(
                413,
                "request_too_large",
                "Webhook request body is too large.",
                request.state.correlation_id,
            )
        body_parts.append(chunk)
    raw_body = b"".join(body_parts)
    try:
        event = request.app.state.openai.webhooks.unwrap(raw_body, request.headers)
    except InvalidWebhookSignatureError:
        return _invalid_signature(request.state.correlation_id)
    log_event(logger, logging.INFO, "webhook_verified", webhook_type=event.type)

    target_status = EVENT_STATUSES.get(event.type)
    if target_status is None:
        return {"received": True}

    redis = request.app.state.redis
    owner_token = secrets.token_hex(16)
    claimed = False
    try:
        claim = await claim_event(
            redis,
            event.id,
            owner_token,
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
            await release_event(redis, event.id, owner_token)
            claimed = False
            raise HTTPException(status_code=503)

        if record.status in TERMINAL_STATUSES:
            if not await mark_processed(redis, event.id, owner_token):
                raise HTTPException(status_code=503)
            claimed = False
            return {"received": True}

        provider = None
        if target_status is JobStatus.COMPLETED:
            log_event(
                logger,
                logging.INFO,
                "openai_request_started",
                operation="retrieve",
                retry_count=0,
            )
            provider = await retry_async(
                lambda: request.app.state.openai.responses.retrieve(event.data.id),
                operation_name="retrieve",
            )
            request.state.openai_request_id = openai_request_id(provider)
            if getattr(provider, "status", None) != "completed":
                await release_event(redis, event.id, owner_token)
                claimed = False
                raise HTTPException(status_code=503)
        record = apply_job_transition(
            record,
            target_status,
            provider=provider if target_status is JobStatus.COMPLETED else None,
        )

        finalization = await finalize_event(redis, event.id, owner_token, record)
        if finalization is FinalizationResult.STALE:
            raise HTTPException(status_code=503)
        if target_status is JobStatus.COMPLETED and finalization is FinalizationResult.UPDATED:
            log_event(
                logger,
                logging.INFO,
                "job_completed",
                correlation_id=record.correlation_id,
                operation="retrieve",
                job_id=record.id,
                openai_request_id=openai_request_id(provider),
            )
        claimed = False
        return {"received": True}
    except RedisError:
        log_event(
            logger,
            logging.ERROR,
            "request_failed",
            operation="webhook",
            status_code=503,
            error_category="redis",
        )
        if claimed:
            await _release_safely(redis, event.id, owner_token)
        raise HTTPException(status_code=503) from None
    except APITimeoutError:
        if claimed:
            await _release_safely(redis, event.id, owner_token)
        raise HTTPException(status_code=504) from None
    except (APIConnectionError, AuthenticationError, RateLimitError):
        if claimed:
            await _release_safely(redis, event.id, owner_token)
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        if claimed:
            await _release_safely(redis, event.id, owner_token)
        if error.status_code >= 500:
            raise HTTPException(status_code=503) from None
        raise
    except Exception:
        if claimed:
            await _release_safely(redis, event.id, owner_token)
        raise
