import uuid

from app.schemas.responses import ResponsesResponse, Usage


def normalize_response(response, correlation_id: str) -> ResponsesResponse:
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
        correlation_id=correlation_id,
    )
