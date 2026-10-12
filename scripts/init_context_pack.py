#!/usr/bin/env python3
"""Scaffold an Agent Context Pack into any target repository.

Usage:
    uv run python scripts/init_context_pack.py /path/to/target-repo [--name "Project Name"] [--dry-run]

This creates/configures:
    - AGENTS.md (root entry point with discovered source modules and conventions)
    - CLAUDE.md and GEMINI.md (@AGENTS.md import stubs)
    - docs/architecture.md (migrates existing root architecture.md if present, or creates template)
    - docs/requirements.md (requirements register R1..Rn + change protocol)
    - docs/decisions.md (architectural decision index)
    - scripts/check_docs.py (tailored drift lint checker)
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

AGENTS_TEMPLATE = """# AGENTS.md

Entry point for AI agents and new contributors. Read this first; open other files only when a branch below tells you to.

## Identity

- **Project:** {name}
- Source directories: {src_summary}
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
| I1 | Core system guarantee | `{primary_dir}` |

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
| R1 | Core system requirement | `{primary_dir}` | `tests/` | done |

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

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    "tests",
    "scripts",
    "docs",
    "assets",
    "artifacts",
}


def get_git_sha(target: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except OSError:
        pass
    return "initial"


def find_source_modules(target: Path) -> list[str]:
    modules = []
    for p in target.rglob("*.py"):
        rel_parts = p.relative_to(target).parts
        if any(ignored in rel_parts for ignored in IGNORE_DIRS):
            continue
        if p.name == "__init__.py":
            continue
        modules.append(p.relative_to(target).as_posix())
    return sorted(modules)


def scaffold(target: Path, name: str | None = None, dry_run: bool = False) -> None:
    target = target.resolve()
    if not target.is_dir():
        print(f"Error: Target directory does not exist: {target}")
        sys.exit(1)

    proj_name = name or target.name
    modules = find_source_modules(target)

    # Determine primary source directories
    top_dirs = sorted({m.split("/")[0] for m in modules if "/" in m})
    src_summary = ", ".join(f"`{d}/`" for d in top_dirs) if top_dirs else "`src/`"
    primary_dir = top_dirs[0] if top_dirs else "src"

    if modules:
        module_rows = "\n".join(f"| `{m}` | Module responsibility |" for m in modules)
    else:
        module_rows = f"| `{primary_dir}/main.py` | Application entry point |"

    sha = get_git_sha(target)
    today = datetime.date.today().isoformat()

    actions = []

    # 1. AGENTS.md
    agents_file = target / "AGENTS.md"
    if not agents_file.exists():
        content = AGENTS_TEMPLATE.format(
            name=proj_name,
            src_summary=src_summary,
            module_rows=module_rows,
        )
        actions.append(("create", agents_file, content))
    else:
        actions.append(("skip", agents_file, "already exists"))

    # 2. CLAUDE.md & GEMINI.md
    for stub in ("CLAUDE.md", "GEMINI.md"):
        f = target / stub
        if not f.exists():
            actions.append(("create", f, "@AGENTS.md\n"))
        else:
            actions.append(("skip", f, "already exists"))

    # 3. docs directory
    docs_dir = target / "docs"
    arch_file = docs_dir / "architecture.md"
    root_arch = target / "architecture.md"

    if not arch_file.exists():
        if root_arch.exists():
            # Migrate existing root architecture.md
            existing_content = root_arch.read_text(encoding="utf-8")
            header = f"> Verified against `{sha}` ({today}).\n\n"
            content = f"# Architecture\n\n{header}{existing_content}"
            actions.append(("create_from_root_arch", arch_file, content))
        else:
            content = ARCHITECTURE_TEMPLATE.format(
                sha=sha,
                date=today,
                primary_dir=primary_dir,
            )
            actions.append(("create", arch_file, content))
    else:
        actions.append(("skip", arch_file, "already exists"))

    req_file = docs_dir / "requirements.md"
    if not req_file.exists():
        actions.append(
            ("create", req_file, REQUIREMENTS_TEMPLATE.format(primary_dir=primary_dir))
        )
    else:
        actions.append(("skip", req_file, "already exists"))

    dec_file = docs_dir / "decisions.md"
    if not dec_file.exists():
        actions.append(("create", dec_file, DECISIONS_TEMPLATE))
    else:
        actions.append(("skip", dec_file, "already exists"))

    # 4. scripts/check_docs.py
    scripts_dir = target / "scripts"
    checker_dest = scripts_dir / "check_docs.py"
    checker_src = Path(__file__).resolve().parent / "check_docs.py"
    if not checker_dest.exists() and checker_src.exists():
        actions.append(("copy", checker_dest, checker_src.read_text(encoding="utf-8")))
    elif checker_dest.exists():
        actions.append(("skip", checker_dest, "already exists"))

    # Execute or print
    print(f"\n--- Scaffolding Plan for: {target.name} ({target}) ---")
    for action, path, data in actions:
        rel_path = path.relative_to(target)
        if action == "skip":
            print(f"  [SKIP]   {rel_path} ({data})")
        elif action in ("create", "create_from_root_arch", "copy"):
            flag = "[MIGRATE]" if action == "create_from_root_arch" else "[CREATE]"
            print(f"  {flag} {rel_path}")
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data, encoding="utf-8")

    if dry_run:
        print("\nDry run completed. No files were written.")
    else:
        print(f"\nSuccessfully initialized Agent Context Pack in {target}!")
        print("Next steps:")
        print("  1. Review AGENTS.md module responsibilities")
        print("  2. Run: python scripts/check_docs.py")


def main():
    parser = argparse.ArgumentParser(description="Scaffold Agent Context Pack")
    parser.add_argument("target", type=Path, help="Target repository root path")
    parser.add_argument("--name", type=str, default=None, help="Project name")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )
    args = parser.parse_args()
    scaffold(args.target, args.name, args.dry_run)


if __name__ == "__main__":
    main()
