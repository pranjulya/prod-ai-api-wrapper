# Phase 0 Project Setup Design

## Scope

Prepare the existing `prod-api-wrapper` workspace for later phases without
adding application code or runtime dependencies.

## Deliverables

- Initialize Git in the current workspace.
- Add a minimal `pyproject.toml` that declares the Python project and its
  required Python version only.
- Add `.gitignore` rules for Python build artifacts, virtual environments,
  test/tool caches, and local environment files.
- Add `.env.example` with every environment variable named in `roadmap.md`,
  using placeholders or safe development defaults.
- Add a concise `README.md` explaining local setup and that real secrets must
  remain in an untracked `.env` file.

## Deliberate Deferrals

FastAPI, Docker Compose, Redis, OpenAI SDK dependencies, application files,
and tests begin in their respective roadmap phases. Phase 0 only establishes
the safe project boundary that those phases require.

## Acceptance Criteria

Git is initialized, no real secret is present in tracked project files, and
the project metadata and sample environment file are ready for subsequent
phases.
