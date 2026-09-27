# Contributing Guidelines

Thank you for your interest in contributing to the **Production API Wrapper**!

This project is built with production-grade engineering standards: strict typed contracts, comprehensive error mapping, atomic Redis state coordination, zero secret leakage, and 100% deterministic, zero-cost automated tests.

---

## Development Workflow

### Prerequisites

- **Python 3.12+**
- **Redis 7+** (or Docker)
- [uv](https://github.com/astral-sh/uv) (recommended) or standard `pip` / `venv`

### Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/your-username/prod-ai-api-wrapper.git
   cd prod-ai-api-wrapper
   ```

2. Create virtual environment and install dependencies:
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install -e ".[dev]"
   ```

3. Copy environment configuration:
   ```bash
   cp .env.example .env
   ```

---

## Quality Standards

Before submitting a Pull Request, ensure:

1. **Linting & Formatting:**
   ```bash
   uv run ruff check app tests
   uv run ruff format --check app tests
   ```

2. **Automated Tests:**
   All unit, integration, and contract tests must pass without external API dependencies:
   ```bash
   uv run pytest
   ```

3. **Code Style:**
   - Follow PEP 8 and project typing conventions.
   - Never log secrets, auth headers, prompts, or raw model outputs.
   - Maintain atomic Redis transaction guarantees (`INCR` + `EXPIRE NX`, Lua scripts).

---

## Pull Request Process

1. Create a descriptive feature branch: `git checkout -b feat/my-enhancement`.
2. Commit your changes with clear, semantic commit messages (e.g. `feat(idempotency): ...`, `fix(retry): ...`).
3. Ensure CI passes on all checks.
4. Submit your PR with a concise summary of changes and trade-offs.
