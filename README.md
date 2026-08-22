# Production API Wrapper

Internal FastAPI wrapper for the OpenAI Responses API. The wrapper holds the
OpenAI key, authenticates internal callers, rate-limits, makes retries safe,
and supports background jobs with signed webhooks.

Requires Python 3.12+ and Redis 7 (`EXPIRE NX`).

## Local run

1. Copy `.env.example` to `.env` and replace placeholder secrets.
2. Start Redis 7, for example: `docker run --rm -p 6379:6379 redis:7-alpine`
3. Install and run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --env-file .env --reload
```

The process does not load `.env` by itself. Always pass `--env-file .env`
(or export the variables).

Health checks:

- `GET /health/live` — process is up (no auth)
- `GET /health/ready` — Redis answers `PING` (no auth)

Business routes need `Authorization: Bearer <WRAPPER_API_KEY>`.

## Docker Compose

```bash
cp .env.example .env
# set OPENAI_API_KEY, OPENAI_WEBHOOK_SECRET, WRAPPER_API_KEY
docker compose up --build
```

Compose overrides `REDIS_URL` to `redis://redis:6379/0`. The image does not
copy `.env`. Redis 7 is required.

## Tests

```bash
pytest
```

The suite fakes OpenAI and Redis. It does not spend money.

## Environment

See `.env.example`. Required: `OPENAI_API_KEY`, `OPENAI_WEBHOOK_SECRET`,
`WRAPPER_API_KEY`, `REDIS_URL`, `OPENAI_ALLOWED_MODELS`.
