import uuid

from fastapi import APIRouter, Request

from app.errors import UnsupportedModelError
from app.schemas.responses import ResponsesRequest, ResponsesResponse, Usage

router = APIRouter()


@router.post("/responses", response_model=ResponsesResponse)
async def create_response(payload: ResponsesRequest, request: Request) -> ResponsesResponse:
    model = payload.model or request.app.state.settings.default_model
    if model not in request.app.state.settings.allowed_models:
        raise UnsupportedModelError()

    kwargs = {"input": payload.input, "model": model}
    for field in ("instructions", "max_output_tokens", "metadata"):
        value = getattr(payload, field)
        if value is not None:
            kwargs[field] = value
    response = await request.app.state.openai.responses.create(**kwargs)
    provider_usage = getattr(response, "usage", None)
    return ResponsesResponse(
        id=f"wrp_resp_{uuid.uuid4()}",
        openai_response_id=getattr(response, "id", None),
        status=getattr(response, "status", None),
        model=getattr(response, "model", None),
        output_text=getattr(response, "output_text", None),
        usage=None
        if provider_usage is None
        else Usage(
            input_tokens=getattr(provider_usage, "input_tokens", None),
            output_tokens=getattr(provider_usage, "output_tokens", None),
            total_tokens=getattr(provider_usage, "total_tokens", None),
        ),
        correlation_id=request.state.correlation_id,
    )
