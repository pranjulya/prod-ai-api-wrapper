from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: Annotated[str, Field(min_length=1, max_length=50_000)]
    instructions: Annotated[str, Field(min_length=1, max_length=10_000)] | None = None
    model: Annotated[str, Field(min_length=1)] | None = None
    max_output_tokens: Annotated[int, Field(ge=1, le=16_384)] | None = None
    metadata: dict[StrictStr, StrictStr] | None = None

    @field_validator("input", "instructions", "model")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Value must not be blank")
        return value

    @field_validator("metadata")
    @classmethod
    def valid_metadata(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        if len(value) > 16 or any(not 1 <= len(key) <= 64 or len(item) > 512 for key, item in value.items()):
            raise ValueError("Metadata is invalid")
        return value


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ResponsesResponse(BaseModel):
    id: str
    openai_response_id: str | None
    status: str | None
    model: str | None
    output_text: str | None
    usage: Usage | None
    correlation_id: str
