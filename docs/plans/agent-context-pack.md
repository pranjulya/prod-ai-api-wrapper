# Agent Context Pack — stop re-analyzing the repo

## Why

Every new requirement currently starts with a full repo exploration. Two focused explore passes this session cost ~830k tokens to re-derive facts the repo already contains (module responsibilities, flows, invariants). Meanwhile 15 design specs carrying the real rationale sit orphaned in `docs/superpowers/specs/` — nothing links them, so agents never find them.

The fix is a small, layered context pack: one always-loaded entry point, two on-demand reference docs, one rationale index, and a drift checker so the map cannot silently rot.

**Success test:** a fresh agent session, given only `AGENTS.md`, can state the middleware order, the Redis key inventory, the terminal-state invariants, and the exact verify commands — and can name which doc/file to touch for a requirement change — without reading `app/`.

## Deliverables

| # | File | Purpose | Loaded |
|---|---|---|---|
| 1 | `AGENTS.md` | Entry point: identity, module map, conventions, verify commands, pointers | always (~110 lines) |
| 2 | `docs/architecture.md` | Deep reference: flows, invariants, Redis state, error map, test map, extension guide | on demand (~300 lines) |
| 3 | `docs/requirements.md` | Requirement register R1..Rn, out-of-scope, change protocol | on demand (~160 lines) |
| 4 | `docs/decisions.md` | ONE line per decision → pointer to the spec that carries the rationale | on demand (~100 lines) |
| 5 | `scripts/check_docs.py` + `tests/test_doc_drift.py` | Fail loudly when docs disagree with code | CI |
| 6 | Wiring edits | README section, CONTRIBUTING pointer, `CLAUDE.md` stub, Makefile, CI step | — |

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

- **Module map** — one line per file, one table row for each of the 22 non-`__init__` modules:
  `main.py` (factory, middleware order Correlation → Authentication → RateLimiting, lifespan wiring) · `config.py` (frozen Settings, fail-fast validation, all env names) · `logging.py` (JSON formatter, `ALLOWED_FIELDS` allowlist, correlation contextvar) · `errors.py` (envelope + handlers) · `api/{health,responses,webhooks}.py` · `clients/{openai,redis}_client.py` · `middleware/{correlation,authentication,rate_limiting}.py` · `schemas/{responses,jobs}.py` · `services/{idempotency,jobs,job_reconciliation,rate_limit,responses,retry,webhooks}.py` · `tests/conftest.py` (FakeRedis implementing each Lua script's branches, autouse `valid_environment` + `fake_redis`) · `scripts/smoke_test.py` (2 billable calls — never in CI).
- **Conventions** (only the non-obvious; nothing derivable from tooling):
  - TDD: failing test first with captured RED output; no production code before a red test.
  - Fakes over mocks: no `unittest.mock`; monkeypatch only `app.main.create_redis`, `app.main.create_openai_client`, `app.api.responses.retry_async`; `FakeRedis.eval` must mirror each Lua branch and return code exactly.
  - Logging: only `log_event(...)` with `ALLOWED_FIELDS`; prompts, outputs, headers, bodies, secrets, provider response IDs, and Redis contents stay out.
  - Redis: every key `wrapper:*`; every multi-key mutation is a pipeline or Lua `EVAL`; per-request owner token via `secrets.token_hex(16)`.
  - State: claim before the provider call; terminal statuses immutable; release pre-completion state only.
  - Commits: Conventional Commits with scope, one task = one commit; stdlib first, no new dependencies.
- **Verify ladder** (copy-pasteable): focused test file → affected test files → `uv run pytest -v --tb=short` → `uv run ruff check app tests scripts` → `make docs-check` when docs or paths change; plus `python -m compileall app`, `git diff --check`. Note that `pytest` needs no Redis and never bills.
- **Artifacts:** task briefs/reports in the gitignored `.superpowers/sdd/<date>-<topic>/`.

## 2. `docs/architecture.md`

Sections, in this order:

1. `> Verified against <short-sha> (<date>). Update in the same commit as any flow/invariant change.`
2. **Shape**: 5 lines + pointer to the README diagram (no second diagram).
3. **Component map**: per module — what it owns, key entry points (function names), and what it may import. Denser than the AGENTS.md one-liners.
4. **Sync flow** `POST /v1/responses`: numbered steps with `file:function` — correlation → bearer compare → rate-limit INCR/EXPIRE → idempotency claim (`SET NX EX processing_ttl`) → allowlist → `retry_async(create)` → `normalize_response` → store replay; and which failures delete the claim vs keep it.
5. **Background flow**: create (job record + reverse index in one pipeline) → poll (`claim_reconciliation`, 5s cooldown, `write_reconciled_job` CAS) → webhook (`claim_event` → `finalize_event` CAS, 72h dedupe).
6. **Invariants** (I1..I12, each testable): SDK `max_retries=0` so one retry layer; auth runs before rate limiting; `/health/*` and webhook paths exempt from bearer; readiness pings Redis while liveness does not; log allowlist + third-party scrubbing; 1 MiB body cap before signature verification; correlation-ID regex; provider 4xx → wrapper `500 internal_error` (deliberate); terminal statuses never overwritten; claim TTL math (`processing_ttl = max(60, 3·timeout + 2·MAX_RETRY_DELAY + 10)`); webhook dedupe TTL outlives job TTL; no scheduled worker anywhere.
7. **Redis state inventory**: pattern | owner module | value | TTL | written by — `wrapper:idempotency:`, `wrapper:job:`, `wrapper:openai-response-job:`, `wrapper:job-reconciliation:`, `wrapper:webhook:event:`, `wrapper:rate-limit:`.
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

1. **Paths exist** — every `app/…`, `tests/…`, `scripts/…`, `Learning/…`, `docs/…` token in those docs resolves on disk.
2. **Redis keys agree both ways** — the set of `wrapper:<name>:` prefixes in `app/**/*.py` equals the set documented in `docs/architecture.md`.
3. **Module coverage** — every `app/**/*.py` (excluding `__init__.py`) has a row in `AGENTS.md`; a new module without a map row fails the build.
4. **Verified-against SHA** — if git is available, the `<short-sha>` in `docs/architecture.md` resolves to a real commit (skips silently otherwise).

Behavior: print each failure with file + detail, exit 1 on any failure, print `docs agree with code` and exit 0 on success. Structure the logic as pure functions (`referenced_paths`, `code_key_prefixes`, `doc_key_prefixes`, `missing_module_rows`) with `main() -> int` so it is unit-testable.

`tests/test_doc_drift.py` — written first (RED), then the script (GREEN). Style mirrors the repo: no mocks, `tmp_path`-based fixtures for the pure functions, plus one real-tree assertion that `main()` exits 0. Load the module by path with `importlib.util.spec_from_file_location` (pytest inserts `tests/` on `sys.path`, so a plain `import scripts.check_docs` would not resolve).

## 6. Wiring edits

- `README.md` — new short section (near "In-Depth Documentation") linking `AGENTS.md`, `docs/architecture.md`, `docs/requirements.md`, `docs/decisions.md`, `docs/superpowers/`. Fixes the orphaned spec corpus.
- `CONTRIBUTING.md` — 4 lines under Development Workflow: start with `AGENTS.md`, change requirements through `docs/requirements.md`, keep docs in the same commit.
- `CLAUDE.md` (new, 1 line: `See AGENTS.md`) — covers tools that look for `CLAUDE.md`.
- `Makefile` — add `docs-check: uv run python scripts/check_docs.py`, add it to the `help` list, and extend `lint` to `ruff check app tests scripts` for parity with CI.
- `.github/workflows/ci.yml` — one step after the Ruff step: `uv run python scripts/check_docs.py`.
- No `.dockerignore`/Dockerfile change needed: the image copies only `pyproject.toml`, `README.md`, `app/`.

---

## Commits (one task each, Conventional Commits)

1. `test(docs): add documentation drift checker` — `tests/test_doc_drift.py`, `scripts/check_docs.py`, Makefile targets, CI step.
2. `docs(context): add architecture, requirement, and decision maps` — the four markdown files.
3. `docs(context): link repository maps from README and CONTRIBUTING` — README, CONTRIBUTING, `CLAUDE.md`.

Branch: `docs/agent-context-pack` off `main`.

## Verification

1. RED first: `uv run pytest tests/test_doc_drift.py -v` fails with the module absent; capture the output before implementing.
2. GREEN: same command passes after `scripts/check_docs.py` lands.
3. Full suite: `uv run pytest -v --tb=short` (expect the existing green suite, ~200 tests).
4. `uv run ruff check app tests scripts` clean.
5. `uv run python scripts/check_docs.py` → `docs agree with code`, exit 0.
6. Mutation checks (prove the checker bites, then restore):
   - delete one Redis key row from `docs/architecture.md` → expect exit 1 naming the missing prefix;
   - rename a documented path token → expect exit 1;
   - remove one module row from `AGENTS.md` → expect exit 1.
7. `python -m compileall app`, `git diff --check`, `git status`.
8. Acceptance (the point of the exercise): start a fresh agent session with only `AGENTS.md` in context and ask (a) "what's the middleware order and what invariant protects terminal job states?" and (b) "where do I record a changed requirement, and which files does it touch?" — both must be answered without reading `app/` or `docs/superpowers/`. Compare tool-token spend against this session's ~830k baseline.

## Risks and non-goals

- **Stale docs are worse than none** — mitigated by the drift checker (paths, keys, modules, SHA) plus one-commit rule.
- **Duplication drift** — the ownership table above is the guard; `AGENTS.md` carries one-liners only, never contract tables.
- Non-goals: rewriting or relocating the phase specs, adding a glossary or ops runbook (deferred until asked), touching `.commandcode/taste/`, converting the register into per-capability spec files.
