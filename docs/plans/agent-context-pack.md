# Agent Context Pack — stop re-analyzing the repo

## Why

Every new requirement currently starts with a full repo exploration. Two focused explore passes this session cost ~830k tokens to re-derive facts the repo already contains (module responsibilities, flows, invariants). Meanwhile 15 design specs carrying the real rationale sit orphaned in `docs/superpowers/specs/` — nothing links them, so agents never find them.

The fix is a small, layered context pack: one always-loaded entry point, two on-demand reference docs, one rationale index, and a drift checker so the map cannot silently rot.

**Success test:** a fresh agent session, starting from `AGENTS.md` and following only the docs it links, can state the middleware order, the Redis key inventory, the terminal-state invariants, and the exact verify commands — and can name which doc/file to touch for a requirement change — without reading `app/`.

## Deliverables

| # | File | Purpose | Loaded |
|---|---|---|---|
| 1 | `AGENTS.md` | Entry point: identity, module map, conventions, verify commands, pointers | always (~110 lines) |
| 2 | `docs/architecture.md` | Deep reference: flows, invariants, Redis state, error map, test map, extension guide | on demand (~300 lines) |
| 3 | `docs/requirements.md` | Requirement register R1..Rn, out-of-scope, change protocol | on demand (~160 lines) |
| 4 | `docs/decisions.md` | ONE line per decision → pointer to the spec that carries the rationale | on demand (~100 lines) |
| 5 | `scripts/check_docs.py` + `tests/test_doc_drift.py` | Fail loudly when docs disagree with code | CI |
| 6 | Wiring edits | README section, CONTRIBUTING pointer, `CLAUDE.md` + `GEMINI.md` import stubs, Makefile, CI step | — |

No duplication rule — each fact has exactly one owner:

| Fact | Owner |
|---|---|
| Wire contract: endpoints, fields, status codes, error codes | `Learning/api-design.md` (existing, authoritative — do not restate) |
| Behavior obligations + how a requirement change is recorded | `docs/requirements.md` (new) |
| Structure, flows, invariants, state model, Redis keys | `docs/architecture.md` (new) |
| Rationale / history | `docs/decisions.md` + `docs/superpowers/specs/` (history, never edited) |
| Product pitch, badges, config table, cost safety | `README.md` (existing) |
| Interview/learning material | `Learning/`, `lessons/`, `reference/` (human-facing) |

---

## 1. `AGENTS.md` (root)

Terse, positive phrasing, one trigger per branch. Outline:

- **Identity** (4 lines): FastAPI gateway in front of the OpenAI Responses API; single source root `app/`; Python 3.12 + `uv`; `tests/` is the behavioral contract; Redis holds all coordination state.
- **Working rule:** treat `docs/architecture.md` as the current map — open `app/` source only for the file being changed. `Learning/*.pdf`, `build_study_guide_pdf.py`, `lessons/*.html` are human study artifacts.
- **Read-by-branch table:**

| Branch | Read |
|---|---|
| Changing a flow, state model, or invariant | `docs/architecture.md` |
| New capability / changed requirement | `docs/requirements.md` |
| "Why is it built this way?" | `docs/decisions.md` |
| API surface change | `Learning/api-design.md`, then `README.md` API sections |
| Historical design intent | `docs/superpowers/specs/<date>-phase-N-*-design.md` |

- **Module map** — a table with one row per module, each row starting with the **full literal repo path** (e.g. `app/api/health.py`, never brace shorthand like `app/api/{health,responses}.py`, which the drift checker cannot match). There are 21 non-`__init__` modules under `app/` (verify with `find app -name '*.py' ! -name '__init__.py' | wc -l`):
  `app/main.py` (factory, middleware order Correlation → Authentication → RateLimiting, lifespan wiring; `CorrelationMiddleware` also converts unhandled exceptions into the `500 internal_error` envelope) · `app/config.py` (frozen Settings, fail-fast validation, all env names) · `app/logging.py` (JSON formatter, `ALLOWED_FIELDS` allowlist, correlation contextvar) · `app/errors.py` (envelope + handlers) · `app/api/health.py` · `app/api/responses.py` · `app/api/webhooks.py` · `app/clients/openai_client.py` · `app/clients/redis_client.py` · `app/middleware/correlation.py` · `app/middleware/authentication.py` · `app/middleware/rate_limiting.py` · `app/schemas/responses.py` · `app/schemas/jobs.py` · `app/services/idempotency.py` · `app/services/jobs.py` · `app/services/job_reconciliation.py` · `app/services/rate_limit.py` · `app/services/responses.py` · `app/services/retry.py` · `app/services/webhooks.py`. Plus two non-`app/` rows: `tests/conftest.py` (FakeRedis implementing each Lua script's branches, autouse `valid_environment` + `fake_redis`) · `scripts/smoke_test.py` (2 billable calls: sync create + background create — never in CI).
- **Conventions** (only the non-obvious; nothing derivable from tooling):
  - TDD: failing test first with captured RED output; no production code before a red test.
  - Fakes over mocks: no `unittest.mock`; monkeypatch only `app.main.create_redis`, `app.main.create_openai_client`, `app.api.responses.retry_async`, `app.api.webhooks.retry_async`; `FakeRedis.eval` must mirror each Lua branch and return code exactly.
  - Logging: only `log_event(...)` with `ALLOWED_FIELDS`; prompts, outputs, headers, bodies, secrets, provider response IDs, and Redis contents stay out.
  - Redis: every key `wrapper:*`; every multi-key mutation is a pipeline or Lua `EVAL`; per-request owner token via `secrets.token_hex(16)`.
  - State: claim before the provider call; terminal statuses immutable; release pre-completion state only.
  - Commits: Conventional Commits with scope, one task = one commit; stdlib first, no new dependencies.
- **Verify ladder** (copy-pasteable): focused test file → affected test files → `uv run pytest -v --tb=short` → `uv run ruff check app tests scripts` → `make docs-check` when docs or paths change; plus `uv run python -m compileall app`, `git diff --check`. Note that `pytest` needs no Redis and never bills.
- **Artifacts:** task briefs/reports in the gitignored `.superpowers/sdd/<date>-<topic>/`.

## 2. `docs/architecture.md`

Sections, in this order:

1. `> Verified against <short-sha> (<date>). Update in the same commit as any flow/invariant change.` The SHA is the **base** commit the doc was checked against. A commit cannot contain its own SHA, so this always points at a parent.
2. **Shape**: 5 lines + pointer to the README diagram (no second diagram).
3. **Component map**: per module — what it owns, key entry points (function names), and what it may import. Denser than the AGENTS.md one-liners.
4. **Sync flow** `POST /v1/responses`: numbered steps with `file:function` — correlation → bearer compare → rate-limit INCR/EXPIRE → `Idempotency-Key` presence check → model allowlist (before any Redis write) → idempotency claim (`SET NX EX processing_ttl`) → `retry_async(create)` → `normalize_response` → store for replay **only when `status == "completed"`** (any other status releases the claim so the client can retry); and which failures delete the claim vs keep it (timeout keeps it; connection/auth/rate-limit/5xx/4xx delete it).
5. **Background flow**: create (`create_job` writes the pending record before the provider call; after it returns, `update_job_with_response_id` writes job record + reverse index in one pipeline) → poll (`claim_reconciliation`, 5s cooldown, `write_reconciled_job` CAS) → webhook (`claim_event` → `finalize_event` CAS, 72h dedupe).
6. **Invariants** (I1..I12, each testable): SDK `max_retries=0` so one retry layer; auth runs before rate limiting; `/health/*` and webhook paths exempt from bearer; readiness pings Redis while liveness does not; log allowlist + third-party scrubbing; 1 MiB body cap before signature verification; correlation-ID regex; provider 4xx → wrapper `500 internal_error` (deliberate); terminal statuses never overwritten; claim TTL math (`processing_ttl = max(60, 3·timeout + 2·MAX_RETRY_DELAY + 10)`); webhook dedupe TTL outlives job TTL; no scheduled worker anywhere.
7. **Redis state inventory**: pattern | owner module | value | TTL | written by — `wrapper:idempotency:`, `wrapper:job:`, `wrapper:openai-response-job:`, `wrapper:job-reconciliation:`, `wrapper:webhook:event:`, `wrapper:rate-limit:`. Note: `wrapper:openai-response-job:` is keyed by a SHA-256 digest of the response ID, and it is written together with the job record in one pipeline by `update_job_with_response_id` (not at job creation, because the response ID isn't known yet).
8. **Error map**: provider failure → wrapper status/code → claim handling, per path (sync, background, poll, webhook).
9. **Test map**: test file ↔ modules covered ↔ what it protects. This is the "changing X → run Y" index.
10. **Extension guide** (the sharp edges): adding an endpoint (schema → service → route → exempt lists in BOTH middlewares → tests → docs); adding a job status (must touch `JobStatus` **and** the status literals inside `WRITE_RECONCILED_JOB_SCRIPT` and `FINALIZE_EVENT_SCRIPT`); adding a Redis key (add to inventory — the drift check enforces it); adding an env var (`app/config.py` + `.env.example` + README table).
11. **Known limits**: no scheduled reconciler; global fixed-window limiter, not per-client; no metrics/log shipping; OpenAI background retention ~10 min vs 24 h job TTL; `services/jobs.py::update_job` is test-only dead code.

## 3. `docs/requirements.md`

- Header: purpose, and the boundary — `Learning/api-design.md` owns the wire contract; this file owns behavior obligations and change tracking.
- **Requirement register**, grouped (Ingress & auth · Limits · Sync · Async & webhooks · Observability · Operations), columns: `ID | Requirement (one line) | Source of truth | Tests | Status`. ~22 rows, e.g.

| ID | Requirement | Source of truth | Tests |
|---|---|---|---|
| R1 | Bearer key required on business routes; constant-time compare | `app/middleware/authentication.py` | `test_authentication.py` |
| R6 | A matching replay returns the stored response with no provider call | `app/services/idempotency.py` | `test_idempotency.py` |
| R13 | Terminal job states are written at most once | `job_reconciliation.py`, `webhooks.py` | `test_job_reconciliation.py`, `test_webhook_service.py` |

- **Out of scope** (explicit, so a new request can be rejected without debate): per-client keys, workers/scheduler, metrics, log shipping, streaming, tool calling, live OpenAI in CI, `python-dotenv`.
- **Change protocol** (numbered, the point of the file): 1) add/edit the R row; 2) if the state model, flow, or an invariant moves, update `docs/architecture.md`; 3) if the wire contract moves, update `Learning/api-design.md` + the README tables + tests; 4) if a new trade-off is hard to reverse and surprising, add a `docs/decisions.md` row (full ADR only when all three ADR criteria hold — keep `docs/adr/` lazy); 5) run the verify ladder; 6) one commit per task.
- **Traceability note:** tests need not embed R-IDs; the register's `Tests` column is the link.

## 4. `docs/decisions.md`

- 3-line preamble: what belongs here, the three ADR criteria, and "index first, promote to `docs/adr/NNNN-*.md` only when a decision is hard to reverse, surprising, and a real trade-off".
- **Index table** — `Decision | Status | Rationale source | Consequence / limit`, ~12 rows: Redis over in-process state; official SDK with `max_retries=0`; fixed-window atomic limiter; single global wrapper key; client-supplied idempotency key + SHA-256 fingerprint; claim TTL = `processing_ttl` (crash recovery in ~100 s); keep the claim on provider timeout; Lua CAS + owner tokens for terminal writes; webhook dedupe TTL 72 h; poll-driven reconciliation with 5 s cooldown and no scheduler; allowlist logging + third-party scrubbing; no `python-dotenv`; non-root `python:3.12-slim` image.
- **Spec corpus index**: one line per file in `docs/superpowers/specs/` (date, phase, what it decided) + the matching plan file. This retires the orphaned-corpus problem — an agent reads one row, not 30 files.

## 5. `scripts/check_docs.py` + `tests/test_doc_drift.py`

Stdlib only, no network, no new dependencies (fits the repo's minimal-surface rule). Lints `AGENTS.md`, `docs/architecture.md`, `docs/requirements.md`, `docs/decisions.md`:

1. **Paths exist** — every `app/…`, `tests/…`, `scripts/…`, `Learning/…`, `docs/…` token in those docs is a **git-tracked** file or directory (`git ls-files`, falling back to disk when git is absent). Checking disk alone passes locally but fails in CI for untracked paths such as the current `lessons/`, `reference/`, `assets/`. Tokens containing placeholder characters (`<`, `>`, `*`, `{`, `}`) or the literal `NNNN` are patterns, not paths, and are skipped. Example: `docs/superpowers/specs/<date>-phase-N-*-design.md`, or the deliberately lazy `docs/adr/NNNN-*.md`.
2. **Redis keys agree both ways** — the set of prefixes matched by `wrapper:[a-z-]+(?::[a-z-]+)*:` in `app/**/*.py` (this must handle the multi-segment `wrapper:webhook:event:` and the hyphenated `wrapper:openai-response-job:` / `wrapper:job-reconciliation:`) equals the set documented in `docs/architecture.md`.
3. **Module coverage** — every `app/**/*.py` (excluding `__init__.py`) appears as a literal path in `AGENTS.md`; a new module without a map row fails the build.
4. **Verified-against SHA** — the `<short-sha>` in `docs/architecture.md` resolves via `git cat-file -e <sha>^{commit}`. **Skip** (with a printed notice, not a failure) when git is absent or `git rev-parse --is-shallow-repository` is `true`. CI's `actions/checkout` defaults to `fetch-depth: 1`, and squash merges orphan branch SHAs, so a hard failure here would turn every CI run red.

Behavior: print each failure with file + detail, exit 1 on any failure, print `docs agree with code` and exit 0 on success. Structure the logic as pure functions (`referenced_paths`, `code_key_prefixes`, `doc_key_prefixes`, `missing_module_rows`) with `main() -> int` so it is unit-testable.

`tests/test_doc_drift.py` — written first (RED), then the script (GREEN). Style mirrors the repo: no mocks, `tmp_path`-based fixtures for the pure functions, plus one real-tree assertion that `main()` exits 0. The real-tree assertion lands in **commit 2**, together with the docs (see Commits), so no commit is red. Load the module by path with `importlib.util.spec_from_file_location` (pytest inserts `tests/` on `sys.path`, so a plain `import scripts.check_docs` would not resolve).

## 6. Wiring edits

- `README.md` — new short section (near "In-Depth Documentation") linking `AGENTS.md`, `docs/architecture.md`, `docs/requirements.md`, `docs/decisions.md`, `docs/superpowers/`. Fixes the orphaned spec corpus.
- `CONTRIBUTING.md` — 4 lines under Development Workflow: start with `AGENTS.md`, change requirements through `docs/requirements.md`, keep docs in the same commit.
- `CLAUDE.md` (new, 1 line: `@AGENTS.md`). Use the import syntax: Claude Code inlines `@path` imports into context, whereas a prose "See AGENTS.md" only works if the agent decides to open the file.
- `GEMINI.md` (new, 1 line: `@AGENTS.md`) — same import mechanism for Gemini CLI. Antigravity, Codex, and Cursor read `AGENTS.md` natively.
- `Makefile` — add `docs-check: uv run python scripts/check_docs.py`, add it to the `help` list, and extend `lint` to `ruff check app tests scripts` for parity with CI.
- `.github/workflows/ci.yml` — one step after the Ruff step: `uv run python scripts/check_docs.py`.
- No `.dockerignore`/Dockerfile change needed: the image copies only `pyproject.toml`, `README.md`, `app/`.

---

## Commits (one task each, Conventional Commits)

1. `test(docs): add documentation drift checker` — `tests/test_doc_drift.py` (pure-function `tmp_path` tests only) and `scripts/check_docs.py`. No CI step and no real-tree test yet: the docs don't exist, so either would make this commit red.
2. `docs(context): add architecture, requirement, and decision maps` — the four markdown files, the real-tree `main() == 0` test, the `make docs-check` target, and the CI step.
3. `docs(context): link repository maps from README and CONTRIBUTING` — README, CONTRIBUTING, `CLAUDE.md`, `GEMINI.md`.

Branch: `docs/agent-context-pack` off `main`. First commit or stash any unrelated work in progress on the current branch. At the time of writing, `app/api/responses.py`, `app/logging.py`, `README.md`, and two test files had uncommitted changes.

## Verification

1. RED first: `uv run pytest tests/test_doc_drift.py -v` fails with the module absent; capture the output before implementing.
2. GREEN: same command passes after `scripts/check_docs.py` lands.
3. Full suite: `uv run pytest -v --tb=short` (expect the existing green suite, 202 tests at the time of writing, plus the new drift tests).
4. `uv run ruff check app tests scripts` clean.
5. `uv run python scripts/check_docs.py` → `docs agree with code`, exit 0.
6. Mutation checks (prove the checker bites, then restore):
   - delete one Redis key row from `docs/architecture.md` → expect exit 1 naming the missing prefix;
   - rename a documented path token → expect exit 1;
   - remove one module row from `AGENTS.md` → expect exit 1.
7. `uv run python -m compileall app`, `git diff --check`, `git status`.
   - Shallow-clone check: `git clone --depth 1 file://$PWD /tmp/shallow && cd /tmp/shallow && uv run python scripts/check_docs.py` → exit 0 with a SHA-skip notice.
8. Acceptance (the point of the exercise): start a fresh agent session with only `AGENTS.md` in context and ask (a) "what's the middleware order and what invariant protects terminal job states?" and (b) "where do I record a changed requirement, and which files does it touch?" — both must be answered without reading `app/` or `docs/superpowers/`. Compare tool-token spend against this session's ~830k baseline.

## Risks and non-goals

- **Stale docs are worse than none** — mitigated by the drift checker (paths, keys, modules, SHA) plus one-commit rule.
- **Duplication drift** — the ownership table above is the guard; `AGENTS.md` carries one-liners only, never contract tables.
- Non-goals: rewriting or relocating the phase specs, adding a glossary or ops runbook (deferred until asked), touching `.commandcode/taste/`, converting the register into per-capability spec files.
