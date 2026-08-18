import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, Request, Response
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
from redis.exceptions import RedisError

from app.errors import IdempotencyConflictError, JobNotFoundError, UnsupportedModelError
from app.logging import log_event
from app.schemas.responses import ResponsesRequest, ResponsesResponse
from app.schemas.jobs import BackgroundJobError, BackgroundJobResponse, JobRecord, JobStatus
from app.services.job_reconciliation import (
    TERMINAL_STATUSES,
    JobWriteResult,
    apply_job_transition,
    claim_reconciliation,
    finish_reconciliation,
    transition_from_provider,
    write_reconciled_job,
)
from app.services.jobs import create_job, delete_job, get_job, update_job_with_response_id
from app.services.retry import openai_request_id, retry_async
from app.services.idempotency import ClaimStatus, claim, delete, redis_key, request_hash, store
from app.services.responses import normalize_response
from app.services.webhooks import processing_ttl

router = APIRouter()
logger = logging.getLogger(__name__)


def _valid_job_id(job_id: str) -> bool:
    if not job_id.startswith("job_"):
        return False
    try:
        value = uuid.UUID(job_id[4:])
    except ValueError:
        return False
    return value.version == 4 and str(value) == job_id[4:].lower()


def _request_kwargs(payload: ResponsesRequest, model: str) -> dict:
    kwargs = {"input": payload.input, "model": model}
    for field in ("instructions", "max_output_tokens", "metadata"):
        value = getattr(payload, field)
        if value is not None:
            kwargs[field] = value
    return kwargs


async def _release_background(redis, idempotency_key: str, job_id: str | None = None) -> None:
    try:
        if job_id is not None:
            await delete_job(redis, job_id)
        await delete(redis, idempotency_key)
    except RedisError:
        pass


def _log_redis_failure(operation: str) -> None:
    log_event(
        logger,
        logging.ERROR,
        "request_failed",
        operation=operation,
        status_code=503,
        error_category="redis",
    )


async def _reconcile_background_job(record: JobRecord, request: Request) -> JobRecord:
    if record.status in TERMINAL_STATUSES or record.openai_response_id is None:
        return record
    redis = request.app.state.redis
    owner_token = secrets.token_hex(16)
    if not await claim_reconciliation(
        redis,
        record.id,
        owner_token,
        processing_ttl(request.app.state.settings.openai_timeout_seconds),
    ):
        return record
    try:
        log_event(logger, logging.INFO, "openai_request_started", operation="retrieve", retry_count=0)
        provider = await retry_async(
            lambda: request.app.state.openai.responses.retrieve(record.openai_response_id),
            operation_name="retrieve",
        )
        request.state.openai_request_id = openai_request_id(provider)
        candidate = transition_from_provider(record, provider)
        if candidate is not None:
            result = await write_reconciled_job(redis, candidate)
            if candidate.status is JobStatus.COMPLETED and result is JobWriteResult.UPDATED:
                log_event(
                    logger,
                    logging.INFO,
                    "job_completed",
                    correlation_id=record.correlation_id,
                    operation="retrieve",
                    job_id=record.id,
                    openai_request_id=openai_request_id(provider),
                )
    except (APITimeoutError, APIConnectionError, RateLimitError):
        pass
    except AuthenticationError:
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        if error.status_code == 404:
            candidate = apply_job_transition(
                record,
                JobStatus.FAILED,
                error=BackgroundJobError(
                    code="background_response_unavailable",
                    message="Background response is no longer available.",
                ),
            )
            await write_reconciled_job(redis, candidate)
        elif error.status_code >= 500:
            pass
        else:
            raise
    finally:
        await finish_reconciliation(redis, record.id, owner_token)
    updated = await get_job(redis, record.id)
    if updated is None:
        raise JobNotFoundError()
    return updated


@router.post("/responses", response_model=ResponsesResponse)
async def create_response(payload: ResponsesRequest, request: Request, idempotency_key: str | None = Header(default=None)) -> ResponsesResponse:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=422)
    idempotency_key = idempotency_key.strip()
    model = payload.model or request.app.state.settings.default_model
    if model not in request.app.state.settings.allowed_models:
        raise UnsupportedModelError()

    kwargs = _request_kwargs(payload, model)
    key = redis_key(idempotency_key)
    fingerprint = request_hash(payload, model)
    try:
        result = await claim(
            request.app.state.redis,
            key=key,
            request_hash_value=fingerprint,
            correlation_id=request.state.correlation_id,
            ttl_seconds=request.app.state.settings.idempotency_ttl_seconds,
        )
        if result.status is ClaimStatus.EXISTING:
            if result.record is None or result.record.request_hash != fingerprint:
                raise IdempotencyConflictError("idempotency_key_reused")
            if result.record.state == "in_progress":
                raise IdempotencyConflictError("idempotency_in_progress")
            replayed = ResponsesResponse.model_validate(result.record.response)
            log_event(
                logger,
                logging.INFO,
                "idempotency_replayed",
                operation="create",
            )
            return replayed
        log_event(logger, logging.INFO, "openai_request_started", operation="create", retry_count=0)
        response = await retry_async(
            lambda: request.app.state.openai.responses.create(**kwargs),
            operation_name="create",
        )
    except RedisError:
        _log_redis_failure("create")
        raise HTTPException(status_code=503) from None
    except APITimeoutError:
        await delete(request.app.state.redis, key)
        raise HTTPException(status_code=504) from None
    except (APIConnectionError, AuthenticationError, RateLimitError):
        await delete(request.app.state.redis, key)
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        if error.status_code >= 500:
            await delete(request.app.state.redis, key)
            raise HTTPException(status_code=503) from None
        await delete(request.app.state.redis, key)
        raise
    request.state.openai_request_id = openai_request_id(response)
    normalized = normalize_response(response, request.state.correlation_id)
    try:
        await store(request.app.state.redis, key=key, request_hash_value=fingerprint, response=normalized, ttl_seconds=request.app.state.settings.idempotency_ttl_seconds)
    except RedisError:
        await delete(request.app.state.redis, key)
        _log_redis_failure("create")
        raise HTTPException(status_code=503) from None
    return normalized


@router.post(
    "/responses/background",
    response_model=BackgroundJobResponse,
    response_model_exclude_none=True,
    status_code=202,
)
async def create_background_response(
    payload: ResponsesRequest, request: Request, idempotency_key: str | None = Header(default=None)
) -> BackgroundJobResponse:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=422)
    model = payload.model or request.app.state.settings.default_model
    if model not in request.app.state.settings.allowed_models:
        raise UnsupportedModelError()

    idempotency_key = idempotency_key.strip()
    key = redis_key(idempotency_key)
    fingerprint = request_hash({"request": payload.model_dump(mode="json"), "background": True}, model)
    settings = request.app.state.settings
    now = datetime.now(timezone.utc)
    job_id = f"job_{uuid.uuid4()}"
    record = JobRecord(
        id=job_id,
        status=JobStatus.PENDING,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.job_ttl_seconds),
        status_url=f"/v1/responses/{job_id}",
        correlation_id=request.state.correlation_id,
    )

    try:
        result = await claim(
            request.app.state.redis,
            key=key,
            request_hash_value=fingerprint,
            correlation_id=request.state.correlation_id,
            ttl_seconds=settings.idempotency_ttl_seconds,
        )
        if result.status is ClaimStatus.EXISTING:
            if result.record is None or result.record.request_hash != fingerprint:
                raise IdempotencyConflictError("idempotency_key_reused")
            if result.record.state == "in_progress":
                raise IdempotencyConflictError("idempotency_in_progress")
            replayed = BackgroundJobResponse.model_validate(result.record.response)
            log_event(
                logger,
                logging.INFO,
                "idempotency_replayed",
                operation="background_create",
                job_id=replayed.id,
            )
            return replayed
        await create_job(request.app.state.redis, record, settings.job_ttl_seconds)
        log_event(logger, logging.INFO, "openai_request_started", operation="background_create", retry_count=0)
        response = await retry_async(
            lambda: request.app.state.openai.responses.create(**_request_kwargs(payload, model), background=True),
            operation_name="background_create",
        )
    except RedisError:
        await _release_background(request.app.state.redis, key, job_id)
        _log_redis_failure("background_create")
        raise HTTPException(status_code=503) from None
    except APITimeoutError:
        await _release_background(request.app.state.redis, key, job_id)
        raise HTTPException(status_code=504) from None
    except (APIConnectionError, AuthenticationError, RateLimitError):
        await _release_background(request.app.state.redis, key, job_id)
        raise HTTPException(status_code=503) from None
    except APIStatusError as error:
        await _release_background(request.app.state.redis, key, job_id)
        if error.status_code >= 500:
            raise HTTPException(status_code=503) from None
        raise

    record = record.model_copy(update={"status": JobStatus.IN_PROGRESS, "openai_response_id": response.id})
    public = BackgroundJobResponse.model_validate(record, from_attributes=True)
    try:
        await update_job_with_response_id(request.app.state.redis, record)
        await store(
            request.app.state.redis,
            key=key,
            request_hash_value=fingerprint,
            response=public,
            ttl_seconds=settings.idempotency_ttl_seconds,
        )
        log_event(
            logger,
            logging.INFO,
            "background_job_created",
            operation="background_create",
            job_id=record.id,
            openai_request_id=openai_request_id(response),
        )
    except RedisError:
        await _release_background(request.app.state.redis, key)
        _log_redis_failure("background_create")
        raise HTTPException(status_code=503) from None
    return public


@router.get(
    "/responses/{job_id}",
    response_model=BackgroundJobResponse,
    response_model_exclude_none=True,
)
async def get_background_response(job_id: str, request: Request, response: Response) -> BackgroundJobResponse:
    if not _valid_job_id(job_id):
        raise JobNotFoundError()
    try:
        record = await get_job(request.app.state.redis, job_id)
        if record is None or record.status is JobStatus.EXPIRED:
            raise JobNotFoundError()
        record = await _reconcile_background_job(record, request)
    except RedisError:
        raise HTTPException(status_code=503) from None
    response.status_code = 202 if record.status in {JobStatus.PENDING, JobStatus.IN_PROGRESS} else 200
    return BackgroundJobResponse.model_validate(record, from_attributes=True)
