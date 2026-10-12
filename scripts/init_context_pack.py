#!/usr/bin/env python3
"""Scaffold an Agent Context Pack into a target repository.

Usage:
    python scripts/init_context_pack.py /path/to/target-repo [--name "Project Name"]

This creates:
    - AGENTS.md (root entry point with discovered source modules)
    - CLAUDE.md and GEMINI.md (@AGENTS.md import stubs)
    - docs/architecture.md (flows, invariants, state models)
    - docs/requirements.md (requirements register R1..Rn + change protocol)
    - docs/decisions.md (architectural decision index)
    - scripts/check_docs.py (drift lint checker)
"""

import argparse
import sys
from pathlib import Path

AGENTS_TEMPLATE = """# AGENTS.md

Entry point for AI agents and new contributors. Read this first; open other files only when a branch below tells you to.

## Identity

- **Project:** {name}
- Single source root `{src_dir}/`.
- Coordination, tests, and configuration details go here.

## Working Rule

Treat `docs/architecture.md` as the current map. Open source files only for the specific file you are changing. Avoid exploring the entire repository on every task.

## Read by Branch

| Branch | Read |
|---|---|
| Changing a flow, state model, or invariant | `docs/architecture.md` |
| New capability / changed requirement | `docs/requirements.md` (follow its change protocol) |
| "Why is it built this way?" | `docs/decisions.md` |

## Module Map

| Path | Owns |
|---|---|
{module_rows}

## Conventions (Non-Obvious Only)

- **TDD:** Write a failing test first, capture output, then implement.
- **Atomic Commits:** One task = one commit; update docs in the same commit as code changes.
- **Dependencies:** Keep dependencies minimal; document architectural choices in `docs/decisions.md`.

## Verify Ladder

```bash
# 1. Focused test
pytest tests/ -q
# 2. Doc drift check
python scripts/check_docs.py
```
"""

ARCHITECTURE_TEMPLATE = """# Architecture

> Verified against `{sha}` ({date}). Update in the same commit as any flow, state, or invariant change.

## 1. System Shape

Overview of services, components, and communication protocols.

## 2. Component Map

Key packages, functions, and cross-module boundaries.

## 3. Invariants

| ID | Invariant | Enforced in |
|---|---|---|
| I1 | Core system guarantee | `{src_dir}/` |

## 4. State & Data Models

Document persistent storage, caches, schemas, and key formats here.

## 5. Error & Failure Handling

Matrix of component failures, fallback strategies, and client-facing error envelopes.
"""

REQUIREMENTS_TEMPLATE = """# Requirements

This file tracks **behavior obligations** and the **formal change protocol**.

## Requirement Register

| ID | Requirement | Source of Truth | Tests | Status |
|---|---|---|---|---|
| R1 | Core system requirement | `{src_dir}/` | `tests/` | done |

## Out of Scope

Explicitly list capabilities that should not be implemented without an architectural review.

## Change Protocol

1. Update or append the row in the register above.
2. If state models, flows, or invariants change, update `docs/architecture.md`.
3. If public APIs or contracts change, update relevant API specs and tests.
4. Run the verify ladder (including `python scripts/check_docs.py`).
5. Commit code and doc changes together in the same commit.
"""

DECISIONS_TEMPLATE = """# Architectural Decisions & Rationale Index

Decisions recorded here represent binding constraints. Full ADRs (`docs/adr/NNNN-*.md`) are created only when a decision is hard to reverse, surprising, and involves a major trade-off.

## Decision Index

| Decision | Status | Rationale / Context | Consequence / Trade-off |
|---|---|---|---|
| Initial Architecture | Accepted | Project inception | Baseline architecture |
"""


def find_source_modules(target: Path, src_dir: str) -> list[str]:
    src_path = target / src_dir
    if not src_path.is_dir():
        return []
    modules = []
    for p in src_path.rglob("*.py"):
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue
        modules.append(p.relative_to(target).as_posix())
    return sorted(modules)


def scaffold(target: Path, name: str | None = None) -> None:
    target = target.resolve()
    if not target.is_dir():
        print(f"Error: Target directory does not exist: {target}")
        sys.exit(1)

    proj_name = name or target.name
    src_dir = "app" if (target / "app").is_dir() else ("src" if (target / "src").is_dir() else target.name)

    modules = find_source_modules(target, src_dir)
    if modules:
        module_rows = "\n".join(f"| `{m}` | Module responsibility |" for m in modules)
    else:
        module_rows = f"| `{src_dir}/main.py` | Application entry point |"

    # 1. AGENTS.md
    agents_file = target / "AGENTS.md"
    if not agents_file.exists():
        agents_file.write_text(
            AGENTS_TEMPLATE.format(name=proj_name, src_dir=src_dir, module_rows=module_rows),
            encoding="utf-8",
        )
        print("Created AGENTS.md")

    # 2. CLAUDE.md & GEMINI.md
    for stub in ("CLAUDE.md", "GEMINI.md"):
        f = target / stub
        if not f.exists():
            f.write_text("@AGENTS.md\n", encoding="utf-8")
            print(f"Created {stub}")

    # 3. docs directory
    docs_dir = target / "docs"
    docs_dir.mkdir(exist_ok=True)

    arch_file = docs_dir / "architecture.md"
    if not arch_file.exists():
        arch_file.write_text(
            ARCHITECTURE_TEMPLATE.format(sha="initial", date="initial", src_dir=src_dir),
            encoding="utf-8",
        )
        print("Created docs/architecture.md")

    req_file = docs_dir / "requirements.md"
    if not req_file.exists():
        req_file.write_text(
            REQUIREMENTS_TEMPLATE.format(src_dir=src_dir),
            encoding="utf-8",
        )
        print("Created docs/requirements.md")

    dec_file = docs_dir / "decisions.md"
    if not dec_file.exists():
        dec_file.write_text(DECISIONS_TEMPLATE, encoding="utf-8")
        print("Created docs/decisions.md")

    # 4. scripts/check_docs.py
    scripts_dir = target / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    checker_dest = scripts_dir / "check_docs.py"
    checker_src = Path(__file__).resolve().parent / "check_docs.py"
    if not checker_dest.exists() and checker_src.exists():
        checker_dest.write_text(checker_src.read_text(encoding="utf-8"), encoding="utf-8")
        print("Copied scripts/check_docs.py")

    print(f"\nSuccessfully scaffolded Agent Context Pack in: {target}")


def main():
    parser = argparse.ArgumentParser(description="Scaffold Agent Context Pack")
    parser.add_argument("target", type=Path, help="Target repository root path")
    parser.add_argument("--name", type=str, default=None, help="Project name")
    args = parser.parse_args()
    scaffold(args.target, args.name)


if __name__ == "__main__":
    main()
