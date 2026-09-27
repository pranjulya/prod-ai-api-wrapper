<div align="center">

# ⚡ Production LLM API Gateway & Resilience Wrapper

**Enterprise-grade FastAPI proxy and resilience ingress layer for the OpenAI Responses API**

[![CI](https://github.com/pranjulya/prod-ai-api-wrapper/actions/workflows/ci.yml/badge.svg)](https://github.com/pranjulya/prod-ai-api-wrapper/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Redis 7](https://img.shields.io/badge/Redis-7.0+-DC382D.svg?logo=redis&logoColor=white)](https://redis.io)
[![Tests](https://img.shields.io/badge/tests-200%20passed-brightgreen.svg)](tests/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<p align="center">
  <a href="#-architecture--system-design">Architecture</a> •
  <a href="#-key-engineering-highlights">Core Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-api-reference--contracts">API Contract</a> •
  <a href="#-resilience--failure-handling">Resilience Matrix</a> •
  <a href="#-testing--verification">Tests</a> •
  <a href="#-in-depth-documentation">Learning & Docs</a>
</p>

</div>

---

## 🎯 Executive Summary & Problem Statement

In enterprise environments, allowing downstream microservices or frontend applications to communicate directly with third-party LLM providers (such as OpenAI) introduces severe operational, financial, and security risks:

1. **Credential Exposure & Cost Spikes:** Exposing master API keys to multiple teams risks key exfiltration and unmetered spend.
2. **Duplicate Billing on Retries:** Transient network timeouts cause clients to retry requests, creating duplicate billable LLM completions.
3. **Cascading Rate-Limit Failures:** Uncoordinated client requests exhaust provider rate limits, degrading service across the entire fleet.
4. **HTTP Connection Exhaustion:** Long-running generative responses lock up HTTP connection pools without asynchronous background job primitives.
5. **Data & PII Leakage:** Sensitive prompts and proprietary completions accidentally leak into centralized log aggregators (Datadog, CloudWatch).
6. **Webhook Vulnerabilities & Race Conditions:** Unverified webhook endpoints and concurrent out-of-order event delivery corrupt background job state.

**Production API Wrapper** solves these challenges by acting as a hardened, high-throughput gateway between internal microservices and OpenAI.

---

## 🏛️ Architecture & System Design

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Internal Clients / Apps                          │
└───────────────────────┬─────────────────────────────▲───────────────────────┘
                        │ HTTP Bearer Auth            │ Polling (202 / 200)
                        │ Idempotency-Key             │ Correlated JSON Logs
                        │ X-Correlation-ID            │
                        ▼                             │
┌─────────────────────────────────────────────────────┴───────────────────────┐
│                        FastAPI Resilience Wrapper                           │
│                                                                             │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐  │
│  │ Correlation & Logging │  │ Bearer Token Auth    │  │ Rate Limiter     │  │
│  │ (Zero PII / Secrets)  │  │ (Constant-Time Guard)│  │ (Atomic Redis)   │  │
│  └───────────────────────┘  └──────────────────────┘  └──────────────────┘  │
│                                                                             │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐  │
│  │ Idempotency Engine    │  │ Bounded Retry Engine │  │ Model Allowlist  │  │
│  │ (SHA-256 Claim/Replay)│  │ (Exp Backoff+Jitter) │  │ (Policy Guard)   │  │
│  └───────────────────────┘  └──────────────────────┘  └──────────────────┘  │
└──────────────┬──────────────────────────────┬───────────────────────────────┘
               │                              │
               │ Synchronous / Async Call     │ Distributed Coordination
               ▼                              ▼
┌──────────────────────────────┐ ┌────────────────────────────────────────────┐
│     OpenAI Responses API     │ │                  Redis 7                   │
│                              │ │                                            │
│  - gpt-5-mini / gpt-4o       │ │  • Distributed Rate-Limit Counters         │
│  - Background Jobs           │ │  • Idempotency Claims & Replay Store       │
│  - Signed Webhook Dispatch   │ │  • Durable Background Job State Machine    │
└──────────────┬───────────────┘ │  • Processed Webhook Deduplication Lock    │
               │                 └─────────────────────▲──────────────────────┘
               │ Signed Webhook (HMAC-SHA256)          │ Atomic Lua Scripts
               └───────────────────────────────────────┘
```

---

## ✨ Key Engineering Highlights

### 🛡️ Zero-Trust Security & PII Protection
* **Secret Isolation:** Upstream OpenAI credentials, webhook secrets, and internal auth keys are never logged, reflected in errors, or exposed to clients.
* **Prompt & Completion Redaction:** Structured logs record metadata, latency, status codes, and correlation IDs, but **never** record prompt inputs or model outputs.
* **Model Allowlisting:** Client requests are constrained to a strictly enforced whitelist (`OPENAI_ALLOWED_MODELS`), preventing unauthorized model consumption.

### 🔁 Distributed Two-Phase Idempotency Engine
* **Request Fingerprinting:** Combines the validated payload and the effective model into a deterministic SHA-256 hash.
* **Distributed Locking (`SET NX EX`):** Claims keys atomically in Redis.
* **Three-Way Resolution:**
  1. *Identical Finished Request:* Instantly replays the stored response with zero upstream latency and zero cost.
  2. *In-Flight Duplicate:* Returns `409 Conflict (idempotency_in_progress)` to prevent duplicate concurrent executions.
  3. *Mismatched Payload Reuse:* Returns `409 Conflict (idempotency_key_reused)`.
* **Automatic Rollback:** Provider failures release in-progress locks, allowing safe client retries.

### ⚡ Atomic Shared Rate Limiting
* Enforces request quotas across multi-worker and multi-instance deployments using Redis fixed windows.
* Atomically executes `INCR` and `EXPIRE NX` within a single Redis transaction to eliminate counter leak bugs.
* Returns HTTP `429` with standardized `Retry-After` headers and structured error envelopes.

### ⏳ Asynchronous Background Engine & Verified Webhooks
* **Non-Blocking Submissions:** Long-running requests return `202 Accepted` with a durable wrapper job ID (`job_<uuid>`) and status URL.
* **Cryptographic Ingress:** `/webhooks/openai` verifies raw HMAC-SHA256 signatures (`webhook-signature`, `webhook-timestamp`, `webhook-id`) before reading bodies or modifying state.
* **Atomic Lua Deduplication:** Concurrent and duplicate webhook deliveries are safely deduplicated using atomic Lua scripts.
* **Race-Condition Safe Reconciliation:** Dual-path synchronization: handles webhooks arriving out of order or before initial Redis records commit.

### 🔄 Adaptive Resilience & Upstream Translation
* **Smart Retry Policy:** Retries only transient faults (network drops, 5xx, timeouts) using exponential backoff with full randomized jitter. Permanent errors (400, 401, 422) fail fast.
* **Error Normalization:** Upstream vendor exceptions are converted into clean, documented HTTP error shapes (`504 upstream_timeout`, `503 upstream_unavailable`).

### 🔍 Cloud-Native Observability & Health Probes
* **Correlated Request Tracing:** Accepts or generates `X-Correlation-ID`, propagating it through response headers, logs, error responses, and job metadata.
* **Kubernetes Probes:**
  * `GET /health/live`: Unauthenticated process liveness (zero dependency).
  * `GET /health/ready`: Deep dependency readiness (verifies Redis connection with `PING`).

---

## 🚀 Quick Start

### Option 1: Docker Compose (Recommended)

Start the API Gateway and Redis 7 with a single command:

```bash
# 1. Clone the repository
git clone https://github.com/pranjulya/prod-ai-api-wrapper.git
cd prod-ai-api-wrapper

# 2. Configure environment variables
cp .env.example .env
# Edit .env with your secrets (OPENAI_API_KEY, WRAPPER_API_KEY, etc.)

# 3. Launch multi-container stack
docker compose up --build
```

The gateway will be live on `http://localhost:8000`.

---

### Option 2: Local Python Environment

**Requirements:** Python 3.12+ and Redis 7 running locally on port 6379.

```bash
# 1. Start Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine

# 2. Setup Virtual Environment
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Run development server
uvicorn app.main:app --env-file .env --reload --port 8000
```

---

## 📡 API Reference & Contracts

All authenticated routes require `Authorization: Bearer <WRAPPER_API_KEY>`.

### 1. Synchronous LLM Generation
`POST /v1/responses`

```bash
curl -X POST http://localhost:8000/v1/responses \
  -H "Authorization: Bearer test-wrapper-key" \
  -H "Idempotency-Key: req-uuid-001" \
  -H "X-Correlation-ID: trace-abc-123" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Summarize the benefits of event-driven architectures.",
    "instructions": "Limit response to two sentences.",
    "model": "gpt-5-mini",
    "max_output_tokens": 150
  }'
```

**Response (`200 OK`):**
```json
{
  "id": "wrp_resp_01J6A8Z9...",
  "openai_response_id": "resp_01J6A8...",
  "status": "completed",
  "model": "gpt-5-mini",
  "output_text": "Event-driven architectures decouple services, enabling independent scaling and enhanced resilience. They improve real-time responsiveness by processing events asynchronously across distributed nodes.",
  "usage": {
    "input_tokens": 28,
    "output_tokens": 34,
    "total_tokens": 62
  },
  "correlation_id": "trace-abc-123"
}
```

---

### 2. Asynchronous Background Generation
`POST /v1/responses/background`

```bash
curl -X POST http://localhost:8000/v1/responses/background \
  -H "Authorization: Bearer test-wrapper-key" \
  -H "Idempotency-Key: req-bg-uuid-002" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Perform deep architectural analysis on distributed transactions.",
    "model": "gpt-5-mini"
  }'
```

**Response (`202 Accepted`):**
```json
{
  "id": "job_01J6B9X7Y8Z9...",
  "status": "pending",
  "created_at": "2026-09-02T12:00:00Z",
  "expires_at": "2026-09-03T12:00:00Z",
  "status_url": "/v1/responses/job_01J6B9X7Y8Z9...",
  "correlation_id": "corr-generated-uuid"
}
```

---

### 3. Poll Background Job Status
`GET /v1/responses/{job_id}`

```bash
curl -X GET http://localhost:8000/v1/responses/job_01J6B9X7Y8Z9... \
  -H "Authorization: Bearer test-wrapper-key"
```

* Returns **`202 Accepted`** while job is `pending` or `in_progress`.
* Returns **`200 OK`** once job is `completed` (with full output payload and token metrics) or reaches a terminal status (`failed`, `cancelled`).
* Returns **`404 Not Found`** for unknown or expired jobs (>24h TTL).

---

### 4. Verified Webhook Ingress
`POST /webhooks/openai`

Receives cryptographically signed terminal lifecycle events from OpenAI:
* Requires valid headers: `webhook-signature`, `webhook-timestamp`, `webhook-id`.
* Enforces 1 MiB maximum payload limit.
* Uses atomic Redis Lua transactions to deduplicate re-deliveries and prevent state regressions.

---

### 5. Health & Kubernetes Probes

| Endpoint | Method | Auth | Dependency Check | Response |
| :--- | :---: | :---: | :--- | :--- |
| `/health/live` | `GET` | None | Process event loop | `200 {"status":"live"}` |
| `/health/ready` | `GET` | None | Redis `PING` | `200 {"status":"ready"}` or `503` |

---

## 🛡️ Resilience & Failure Handling

| Scenario / Failure Mode | System Behavior | HTTP Status |
| :--- | :--- | :---: |
| **Missing / Invalid Bearer Key** | Request rejected at middleware before hitting business logic | `401 Unauthorized` |
| **Missing Idempotency Key** | Request rejected at schema validation boundary | `422 Unprocessable` |
| **Unapproved Model Requested** | Request rejected by model allowlist policy guard | `400 Bad Request` |
| **Rate Limit Exceeded** | Fixed-window counter trips; returns `Retry-After` header | `429 Too Many Requests` |
| **Idempotency Replay** | Identical payload returns cached result immediately | `200 OK` |
| **Idempotency Collision** | Same key reused with different body or model | `409 Conflict` |
| **Concurrent In-Flight Key** | Same key submitted while original execution is running | `409 Conflict` |
| **OpenAI Upstream Outage / 5xx** | Bounded retries with exponential backoff & jitter; maps to safe wrapper error | `503 Service Unavailable` |
| **OpenAI Upstream Timeout** | Exceeds timeout budget; cleans up in-progress idempotency locks | `504 Gateway Timeout` |
| **Redis Outage** | Handled gracefully without crashing process; readiness probe turns red | `503 Service Unavailable` |
| **Forged Webhook** | Invalid HMAC signature rejected before parsing or DB lookup | `401 Unauthorized` |
| **Duplicate Webhook Delivery** | Processed atomically once via Lua script; redundant events return `200` | `200 OK` |

---

## ⚙️ Configuration Reference

All settings are configured via environment variables and strictly validated at application startup:

| Variable | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| `OPENAI_API_KEY` | String | *Required* | Upstream OpenAI Secret API Key (never logged or exposed) |
| `OPENAI_WEBHOOK_SECRET` | String | *Required* | HMAC secret used to verify OpenAI webhook signatures |
| `WRAPPER_API_KEY` | String | *Required* | Bearer token required for internal callers |
| `REDIS_URL` | String | *Required* | Redis connection URL (`redis://...` or `rediss://...`) |
| `OPENAI_ALLOWED_MODELS`| CSV | `gpt-5-mini` | Comma-separated allowlist of permitted models |
| `OPENAI_DEFAULT_MODEL` | String | `gpt-5-mini` | Default model when not specified in client payload |
| `OPENAI_TIMEOUT_SECONDS`| Int | `30` | Maximum timeout before terminating upstream requests |
| `RATE_LIMIT_REQUESTS` | Int | `60` | Max requests allowed within the rate limit window |
| `RATE_LIMIT_WINDOW_SECONDS`| Int | `60` | Duration of the rate limit window |
| `JOB_TTL_SECONDS` | Int | `86400` | Expiration TTL for background job state (24 hours) |
| `IDEMPOTENCY_TTL_SECONDS` | Int | `86400` | Expiration TTL for cached idempotency records (24 hours)|
| `LOG_LEVEL` | String | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 🧪 Testing & Verification

The test suite contains **200 comprehensive unit, integration, and contract tests**. All tests use deterministic in-memory fakes for OpenAI and Redis, ensuring **zero external network requests and zero billing costs**.

```bash
# Run the complete test suite
pytest

# Run tests with coverage and verbose output
pytest -v --tb=short

# Run smoke test script against running instance
./scripts/smoke_test.py --url http://localhost:8000 --key test-wrapper-key
```

### Test Coverage Highlights
* **Authentication & Ingress Security (`test_authentication.py`):** Bearer token validation, empty/malformed headers, timing attacks.
* **Rate Limiting Engine (`test_rate_limiting.py`, `test_rate_limit_service.py`):** Concurrency tests, window boundary transitions, Redis atomic pipelines.
* **Idempotency Lifecycle (`test_idempotency.py`, `test_idempotency_service.py`):** Replay verification, body mismatch collisions, race conditions, rollback on failure.
* **Background Jobs & Webhook Engine (`test_background_responses.py`, `test_webhooks.py`, `test_job_reconciliation.py`):** Signature verification, out-of-order deliveries, payload limits, state transitions.
* **Retry Engine & Error Translation (`test_retry.py`, `test_upstream_errors.py`):** Backoff calculation, full jitter randomness, status code mapping.
* **Observability & Logging (`test_logging.py`):** Asserts zero secret or prompt leakage in structured JSON records.

---

## 📚 In-Depth Documentation & Study Materials

Explore the documentation guides inside the [`Learning/`](Learning/) directory:

* [**Learning Path & Concepts**](Learning/learning-path.md): Step-by-step breakdown of how each distributed systems concern was added.
* [**API Contract Specifications**](Learning/api-design.md): In-depth schema and validation rules.
* [**Engineering Questions & Answers**](Learning/questions-and-answers.md): 30+ deep-dive architectural trade-offs (e.g. why Redis over in-memory, why atomic Lua over optimistic locking, why omit prompt logging).
* [**Interview Study Guide (PDF)**](Learning/interview-study-guide.pdf): Printable technical study guide covering distributed systems design for LLM gateways.

---

## 🛠️ Developer Tooling & Makefile

```bash
make help         # View all available developer commands
make test         # Execute test suite
make lint         # Run ruff code linter
make format       # Auto-format codebase with ruff
make run          # Start local API with live reloading
make docker-up    # Build & launch container stack
make docker-down  # Stop and tear down containers
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
