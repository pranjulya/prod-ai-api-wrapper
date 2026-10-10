# Student Glossary: AI API Gateway in Plain English

For non-technical readers. Every term has a one-line meaning and a real-life picture.
Source project: this repo, a "wrapper" that sits between company apps and OpenAI.

## 1. The Big Picture (read this first)

Imagine a hotel.
- **Guests** = your company's apps.
- **Kitchen** = OpenAI (the AI).
- **Front desk** = our wrapper. Guests never enter the kitchen. They talk to the front desk. The desk checks who they are, limits how much they order, and makes sure nobody is charged twice.

| Hotel idea | Technical name | Why it matters |
|---|---|---|
| Front desk | Gateway / wrapper | One safe door to the AI |
| Room key | API key | Proves who you are. Never share it |
| Order ticket number | Idempotency key | Same ticket = same order, never charged twice |
| Order limit per hour | Rate limiting | Stops one guest using everything |
| "Your order is being cooked" slip | Background job | Come back later for the result |
| Kitchen calls the desk when ready | Webhook | The AI tells us when it finishes |
| Notebook shared by all desk staff | Redis | Fast shared memory |

## 2. Core Terms

| Term | Simple meaning | Everyday example |
|---|---|---|
| **API** | A menu of requests one program can make to another | A restaurant menu |
| **API key** | A secret password for a program | Hotel room key |
| **Endpoint** | One specific address on an API | One item on the menu |
| **Request / Response** | Question sent / answer returned | Order / meal |
| **HTTP** | The language browsers and apps use to talk over the internet | Postal system rules |
| **JSON** | A neat text format for data: `{"name": "Asha"}` | A filled-in form |
| **LLM** | Large Language Model, an AI that writes text | A very well-read assistant |
| **Prompt** | The instruction you give the AI | The question you ask |
| **Token** | A small piece of text the AI counts and bills by (about 3/4 of a word) | Taxi meter ticks |
| **Model** | A specific AI version (e.g. gpt-4o) | Chef A vs Chef B |
| **Proxy / Gateway** | A middle service that passes requests along safely | Receptionist |

## 3. HTTP Status Codes (the "traffic lights")

| Code | Name | Meaning |
|---|---|---|
| 200 | OK | Done, here is your answer |
| 202 | Accepted | Got it, still working. Check back |
| 400/422 | Bad request | Your question was malformed |
| 401 | Unauthorized | Who are you? Wrong or missing key |
| 404 | Not found | That does not exist |
| 409 | Conflict | Same request is already running |
| 429 | Too many requests | Slow down (rate limit) |
| 500 | Server error | Our fault |
| 502/503/504 | Upstream problem | The AI side is down, busy or slow |

Rule of thumb: 2xx = success, 4xx = you made a mistake, 5xx = we made a mistake.

## 4. Reliability Concepts (what makes it "production-grade")

| Term | Plain meaning | Why you should care |
|---|---|---|
| **Idempotency** | Doing the same thing twice has the same result as once | Prevents double charges when a phone retries a payment |
| **Retry** | Try again after a failure | Networks glitch. Retrying fixes small problems |
| **Exponential backoff** | Wait 1s, then 2s, then 4s between retries | Stops hammering a struggling server |
| **Jitter** | Add random wait time | Stops 1,000 apps retrying at the exact same second |
| **Bounded retry** | A maximum number of retries | Avoids retrying forever |
| **Timeout** | Give up waiting after N seconds | A call must not hang for ever |
| **Rate limit** | Max requests per time window | Fair use, cost control |
| **Fixed window** | Count requests per clock minute | Simple counter that resets |
| **Atomic operation** | All-or-nothing, cannot be interrupted | Two people cannot grab the last ticket at once |
| **Race condition** | Two things happen at once and break each other | Two cashiers sell the same last item |
| **Graceful failure** | Fail with a clear message, not a crash | "Sold out" instead of a blank screen |
| **Transient vs permanent error** | Temporary (retry) vs final (do not retry) | Busy line vs wrong number |

## 5. Security Concepts

| Term | Plain meaning |
|---|---|
| **Authentication** | Proving who you are (showing ID) |
| **Authorization** | What you are allowed to do (VIP area access) |
| **Bearer token** | A secret sent in a header: "whoever bears this gets in" |
| **Constant-time comparison** | Compare secrets so timing never leaks hints to attackers |
| **Secret / environment variable** | Passwords stored outside the code, never in Git |
| **`.env` file** | Local file holding secrets. Must be in `.gitignore` |
| **HMAC / signature** | A tamper-proof stamp proving a message is genuine |
| **SHA-256** | A one-way fingerprint of data. Same input, same fingerprint |
| **PII** | Personal Identifiable Information (names, emails). Keep out of logs |
| **Allowlist** | Only approved items pass (e.g. approved AI models) |

## 6. Tools and Technology Used

| Tool | What it is | One-line role here |
|---|---|---|
| **Python** | Programming language | Writes the service |
| **FastAPI** | Python web framework | Builds the API quickly, auto-validates |
| **Uvicorn** | Web server | Actually listens for requests |
| **Pydantic** | Data checker | Rejects badly shaped input |
| **Redis** | Very fast in-memory database | Shared counters, job state, dedupe |
| **TTL** | Time To Live | Data auto-deletes after a set time |
| **Lua script (in Redis)** | Mini program run inside Redis | Makes multi-step actions atomic |
| **OpenAI Responses API** | OpenAI's text generation API | The "kitchen" |
| **Docker** | Packages an app with everything it needs | "Works on my machine" becomes "works everywhere" |
| **Docker Compose** | Starts several containers together | Starts API plus Redis with one command |
| **pytest** | Test runner | Proves the code works |
| **Ruff** | Code style checker | Keeps code tidy |
| **GitHub Actions / CI** | Robot that runs tests on every change | Catches bugs early |
| **uv / pyproject.toml** | Python package manager / project settings | Installs the right libraries |

## 7. Async and Background Work

| Term | Plain meaning | Example |
|---|---|---|
| **Synchronous** | Wait for the answer now | Phone call |
| **Asynchronous (async)** | Do other things while waiting | Email |
| **Background job** | Long task handled later; you get a ticket | Dry cleaning |
| **Polling** | Keep asking "ready yet?" | Checking the oven |
| **Webhook** | The other side calls you when ready | Cleaner phones you |
| **Job state machine** | Fixed stages: queued, running, completed or failed | Parcel tracking |
| **Deduplication** | Ignore repeated copies of the same event | Ignore a duplicate text |
| **Reconciliation** | Double-check state when a message was missed | Matching bank statement to receipts |

## 8. Observability (seeing what the system does)

| Term | Plain meaning |
|---|---|
| **Logging** | A diary of what happened |
| **Structured (JSON) logs** | Diary entries in a machine-searchable format |
| **Correlation ID** | A tracking number on one request, visible in every log line |
| **Liveness check** | "Is the app running?" |
| **Readiness check** | "Is the app AND its dependencies (Redis) ready for traffic?" |
| **Middleware** | A checkpoint every request passes through (auth, logging, limits) |
| **Latency** | How long a request takes |
| **Metrics / monitoring** | Numbers and dashboards on system health |

## 9. How One Request Flows (6 steps)

1. App sends a request with its **bearer token** and an **idempotency key**.
2. **Correlation ID** is attached for tracing.
3. **Auth** checks the token.
4. **Rate limiter** (Redis) checks the quota.
5. **Idempotency** checks: seen this key before? Return the saved answer.
6. Wrapper calls OpenAI with **retries and timeout**, returns a clean response. If long, it returns **202** plus a job ID. The result arrives by **webhook** or the app **polls**.

## 10. Six Real Problems This Project Solves

| Problem | Fix | Term |
|---|---|---|
| Master key leaks | Only the wrapper holds it | Secret management |
| Double billing on retry | Same key returns saved answer | Idempotency |
| One team uses all quota | Per-client limit | Rate limiting |
| Slow AI jobs block the app | Ticket now, answer later | Background jobs |
| Private data in logs | Log only safe fields | PII protection |
| Fake or repeated callbacks | Verify signature, dedupe | HMAC + deduplication |

## 11. Teaching Mental Models

1. **Never trust, always verify.** Check identity, input and signatures.
2. **Assume failure.** Networks fail. Design so failure is safe.
3. **Retries need safety.** Retry without idempotency equals duplicate cost.
4. **Share state in one place.** Many servers need one source of truth (Redis).
5. **If you cannot see it, you cannot fix it.** Logs plus correlation IDs.

## 12. Quiz Yourself

1. Why do we not give the OpenAI key to every app?
2. What does a 429 mean, and what should the app do?
3. Why add random jitter to retries?
4. Difference between polling and webhook?
5. What does idempotency save you from?

Answers are in section 4, 5 and 7 above. Go deeper in `learning-path.md`, `api-design.md` and `questions-and-answers.md`.
