from openai import AsyncOpenAI

from app.config import Settings


def create_openai_client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        max_retries=0,
        timeout=settings.openai_timeout_seconds,
    )
