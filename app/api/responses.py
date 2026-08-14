import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, Request, Response
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError, RateLimitError
from redis.exceptions import RedisError

from app.errors import IdempotencyConflictError, JobNotFoundError, UnsupportedModelError
from app.schemas.responses import ResponsesRequest, ResponsesResponse
from app.schemas.jobs import BackgroundJobResponse, JobRecord, JobStatus
from app.services.jobs import create_job, delete_job, get_job, update_job_with_response_id
from app.services.retry import retry_async
from app.services.idempotency import ClaimStatus, claim, delete, redis_key, request_hash, store
from app.services.responses import normalize_response

router = APIRouter()


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
            return ResponsesResponse.model_validate(result.record.response)
        response = await retry_async(lambda: request.app.state.openai.responses.create(**kwargs))
    except RedisError:
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
    normalized = normalize_response(response, request.state.correlation_id)
    try:
        await store(request.app.state.redis, key=key, request_hash_value=fingerprint, response=normalized, ttl_seconds=request.app.state.settings.idempotency_ttl_seconds)
    except RedisError:
        await delete(request.app.state.redis, key)
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
            return BackgroundJobResponse.model_validate(result.record.response)
        await create_job(request.app.state.redis, record, settings.job_ttl_seconds)
        response = await retry_async(
            lambda: request.app.state.openai.responses.create(**_request_kwargs(payload, model), background=True)
        )
    except RedisError:
        await _release_background(request.app.state.redis, key, job_id)
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
    except RedisError:
        await _release_background(request.app.state.redis, key)
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
    except RedisError:
        raise HTTPException(status_code=503) from None
    if record is None or record.status is JobStatus.EXPIRED:
        raise JobNotFoundError()
    response.status_code = 202 if record.status in {JobStatus.PENDING, JobStatus.IN_PROGRESS} else 200
    return BackgroundJobResponse.model_validate(record, from_attributes=True)
