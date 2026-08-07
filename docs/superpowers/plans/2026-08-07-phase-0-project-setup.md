# Phase 0 Project Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the repository for safe future development without adding application code or dependencies.

**Architecture:** The project root owns only its Python metadata, documented environment-variable names, and repository hygiene in this phase. Real configuration belongs to an untracked `.env` file; `.env.example` is documentation only.

**Tech Stack:** Python 3.12+, setuptools, Git.

## Global Constraints

- Use `/Users/pranjulyabajpai/src/genAI/prod-api-wrapper` as the project root.
- Do not add FastAPI, Docker, Redis, OpenAI, or test dependencies in Phase 0.
- Never store real API keys or webhook secrets in tracked files.
- All future project files remain inside this project root.

---

### Task 1: Establish project metadata and secret-safe defaults

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`

**Interfaces:**
- Consumes: The environment-variable names in `roadmap.md`.
- Produces: Standard Python project metadata, an untracked local environment-file convention, and documented placeholder configuration for future phases.

- [ ] **Step 1: Create the project metadata**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "prod-api-wrapper"
version = "0.1.0"
description = "Internal FastAPI wrapper for the OpenAI Responses API"
readme = "README.md"
requires-python = ">=3.12"
dependencies = []
```

- [ ] **Step 2: Add ignore rules and documented environment placeholders**

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
build/
*.egg-info/
```

```dotenv
OPENAI_API_KEY=replace-with-openai-api-key
OPENAI_WEBHOOK_SECRET=replace-with-openai-webhook-secret
WRAPPER_API_KEY=replace-with-wrapper-api-key
REDIS_URL=redis://redis:6379/0
OPENAI_ALLOWED_MODELS=gpt-5-mini
OPENAI_DEFAULT_MODEL=gpt-5-mini
OPENAI_TIMEOUT_SECONDS=30
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
JOB_TTL_SECONDS=86400
IDEMPOTENCY_TTL_SECONDS=86400
LOG_LEVEL=INFO
```

- [ ] **Step 3: Add the setup README**

```markdown
# Production API Wrapper

An internal, production-style FastAPI wrapper for the OpenAI Responses API.

## Phase 0 setup

1. Use Python 3.12 or newer.
2. Copy `.env.example` to `.env`.
3. Replace only the placeholder values in `.env` with real credentials.

`.env` is ignored by Git. Never commit API keys or webhook secrets.
```

- [ ] **Step 4: Run the Phase 0 verification**

Run: `test -f pyproject.toml && test -f .gitignore && test -f .env.example && test -f README.md && git check-ignore -q .env && ! git ls-files --error-unmatch .env >/dev/null 2>&1`

Expected: exit status `0`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore .env.example README.md
git commit -m "chore: prepare project foundation"
```
