# Residuals — `prod-ai-api-wrapper`

A snapshot of unfinished work, documentation drift, and deferred items still
present in the repository. The implementation code itself is clean — no TODOs,
no half-implemented functions, no commented-out blocks, no secrets in tracked
files. The residuals below are concentrated in documentation, plans, and the
roadmap backlog.

---

## High priority

- **`.commandcode/taste/taste.md`** — empty 0-byte tracked file, no documented purpose.
  Either fill with content or remove from the repo.
- **`scripts/smoke_test.py`** — missing. Called for in `roadmap.md:130` and
  `roadmap.md:727-731` as an optional live OpenAI smoke test that must not run
  automatically. The interview study guide (`Learning/build_study_guide_pdf.py:1256`)
  also lists this as outstanding.
- **No portfolio demonstration artifact** — roadmap Phase 18 (`roadmap.md:912-922`)
  lists nine demonstration steps (sync, background, polling, idempotent retry, etc.)
  and Phase 19 calls for recording the portfolio demonstration. Nothing in the repo
  records this.

## Medium priority

- **`pyproject.toml:21-25`** — `reportlab` (used by `Learning/build_study_guide_pdf.py`)
  is not declared. `pip install -e ".[dev]"` cannot run the PDF builder. Add a
  `[project.optional-dependencies].docs` group or move the builder script out of
  `Learning/`.
- **`docs/superpowers/plans/*.md`** — every plan file uses `- [ ]` checkboxes and
  none are checked, even for phases that shipped. Either mark completed steps or
  note in each plan that all steps were executed.
- **`Learning/build_study_guide_pdf.py:1255-1258`** — the PDF admits Docker was
  missing. Docker is now shipped, but the slide still says it isn't, so the
  published study guide under-reports current state.
- **`docs/superpowers/specs/2026-08-12-phase-8-openai-responses-design.md:67`** —
  says incomplete-response handling was "deferred to Phase 9". It shipped
  (`app/api/responses.py:109-122`, `app/services/job_reconciliation.py:18-25`) but
  the spec was never updated.
- **`docs/superpowers/plans/2026-08-20-blockers-and-local-operations.md`** — only a
  12-line outline ("Task 1: Claim TTL... Task 4: Docker, Compose, README") with no
  step content, unlike every other plan file. The accompanying design file is fully
  written.

## Low priority

- **`app/services/__init__.py`, `app/clients/__init__.py`, `app/middleware/__init__.py`,
  `app/schemas/__init__.py`** — 0-byte package markers. `app/__init__.py` and
  `app/api/__init__.py` have a one-line docstring; these do not. Required for
  Python package discovery so they cannot simply be removed.
- **Duplicate `pytestmark = pytest.mark.filterwarnings(...)`** in multiple test
  files (`tests/test_authentication.py:10-12`, `tests/test_health.py:7-9`, others).
  Could be folded into `pyproject.toml`'s single `filterwarnings` entry.
- **`docs/superpowers/plans/2026-08-18-background-job-poll-reconciliation.md:24`** —
  describes the study-guide PDF as "untracked". It is tracked.
- **`docs/superpowers/specs/2026-08-13-phase-9-upstream-errors-design.md:52`** —
  "live OpenAI integration tests remain deferred". Still true and consistent, just
  flagged as a known residual.
- **No background-job scheduled reconciler** — `Learning/questions-and-answers.md:94-95`
  flags this as a known gap: missed webhook combined with no client polling leaves
  jobs stuck in `in_progress` until TTL expiry. Roadmap Phase 17 did not add it.
- **Per-client API keys / multi-tenant improvements** — listed as non-goals in
  `docs/superpowers/specs/2026-08-20-blockers-and-local-operations-design.md:67`.
  Wrapper is intentionally single-tenant; revisit only if multi-tenant is required.
- **OpenAI model-name and token-usage logging** — `docs/superpowers/specs/2026-08-16-phase-14-structured-json-logging-design.md:201-202`
  explicitly omits these fields. Useful debugging fields for a future iteration.
- **`.env.example:1-3`** — placeholder values look like real secret formats to a
  casual reader. Documented and intentional; ensure CI never boots from it
  directly.
- **Phase 20 final-review checklist** — `roadmap.md:957-965` requires "No `TODO`
  or `TBD` remains" (line 959) and "Architecture matches the actual implementation."
  Not formally passed because of the empty `.commandcode/taste/taste.md` above.

---

## Summary

No dead code, no half-implemented functions, no commented-out blocks, no secrets
in tracked files. The codebase is finished; the residuals are missing
*documents*, not missing *code*. The roadmap and superpowers plans are working
documents that have not been retired, and that is where most of the cleanup work
lies.
