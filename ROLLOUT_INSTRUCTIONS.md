# AGENT CONTEXT PACK: MULTI-REPO ROLLOUT INSTRUCTIONS

> **How to use this file:**
> Provide this entire document as the prompt/instruction to your AI assistant (e.g., ChatGPT, Claude, Antigravity) when working across the repositories in `/Users/pranjulyabajpai/src/genAI/`.

---

```markdown
# MISSION
You are a Senior Solutions Architect. Your mission is to implement a production-grade **Agent Context Pack & Documentation Drift Gate** across repositories in `/Users/pranjulyabajpai/src/genAI/`.

## THE GOAL
Stop AI agents from burning tokens re-exploring codebases on every task.
Establish a strict 4-layer context system with a self-verifying drift checker in every repository:
1. `AGENTS.md` (root entry point: identity, literal module map, non-obvious conventions, verify ladder)
2. `CLAUDE.md` and `GEMINI.md` (one-line `@AGENTS.md` import stubs)
3. `docs/architecture.md` (system shape, flows, state models, invariants I1..In, error matrix)
4. `docs/requirements.md` (requirements register R1..Rn, out-of-scope boundaries, change protocol)
5. `docs/decisions.md` (architectural decisions index linking to specs/rationale)
6. `scripts/check_docs.py` (zero-dependency CI drift checker that guarantees docs never rot)
7. `Makefile` and `.github/workflows/ci.yml` (wire the `docs-check` command into standard workflow)

---

## REPOSITORY LIST TO PROCESS
Check each directory in `/Users/pranjulyabajpai/src/genAI/`:
- `adaptive-rag-router`
- `automated-eval-harness`
- `cited-RAG-Bot`
- `eval-driven-rag`
- `fort-knox-rag`
- `graphrag-multi-hop`
- `h-i-t-l`
- `local-inference-server`
- `portfolio-site`
- `rag-production-console`
- `security-guardrail-middleware`
- `streaming-copilot-ui`
- `token_cost_estimator`
- `traced-deployment-pipeline`
- `validated-JSON-Agent`
- *(Skip `prod-api-wrapper` as it is already the reference implementation)*

---

## EXECUTION STEPS FOR EACH REPOSITORY

For each repository in the list above, execute these steps sequentially:

### Step 1: Analyze Repository Layout
1. Determine the source root directory (`app/`, `src/`, `api/`, or top-level python packages).
2. Check for existing architecture/documentation files at root or in `docs/`:
   - e.g., `architecture.md`, `BUG_BOUNDARY.md`, `THREAT_MODEL.md`, `KNOWN_LIMITATIONS.md`, `PRD.md`.
3. Discover all source code modules (`find <src_dir> -name '*.py' ! -name '__init__.py'`).

---

### Step 2: Create `AGENTS.md` (at repo root)
Follow this exact format (<120 lines, no verbose narrative):

```markdown
# AGENTS.md

Entry point for AI agents and new contributors. Read this first; open other files only when a branch below tells you to.

## Identity

- **Project:** <Project Name>
- <One-line summary of system purpose, framework (e.g. FastAPI, LangChain, LlamaIndex), and data tier (e.g. Postgres, Neo4j, Qdrant)>
- Single source root `<src_dir>/`.
- `tests/` is the behavioral contract.

## Working Rule

Treat `docs/architecture.md` as the current map. Open source files only for the specific file you are changing. Never perform full-repo exploratory scans.

## Read by Branch

| Branch | Read |
|---|---|
| Changing a flow, state model, or invariant | `docs/architecture.md` |
| New capability / changed requirement | `docs/requirements.md` (follow its change protocol) |
| "Why is it built this way?" | `docs/decisions.md` |

## Module Map

| Path | Owns |
|---|---|
<!-- CRITICAL: Every row MUST start with the full literal path from repo root. No brace shorthand! -->
| <src_dir>/main.py | Entrypoint, routing, dependency wiring |
| <src_dir>/... | <5-10 word description of module responsibility> |

## Conventions (Non-Obvious Only)

- **TDD:** Write failing test first, capture output, then implement.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`); update documentation in the same commit as code changes.
- **Dependencies:** Keep dependencies minimal; document major additions in `docs/decisions.md`.

## Verify Ladder

```bash
uv run pytest tests/ -q                 # or project test runner
make docs-check                         # enforce documentation consistency
```
```

---

### Step 3: Create Multi-Agent Compatibility Stubs
Create `CLAUDE.md` and `GEMINI.md` at repo root with the exact one-line content:
```markdown
@AGENTS.md
```
*(Claude Code and Gemini CLI will automatically inline `AGENTS.md`, while Cursor and Antigravity read it directly).*

---

### Step 4: Create `docs/architecture.md`
If a root `architecture.md` exists, migrate its contents into `docs/architecture.md` and remove the redundant root file. Include:
```markdown
# Architecture

> Verified against `<current-git-short-sha>` (<YYYY-MM-DD>). Update in the same commit as any flow, state, or invariant change.

## 1. Shape
- Summary of architecture, deployment topology, and core data flow.

## 2. Component Map
- Key packages and their relationships.

## 3. Invariants
| ID | Invariant | Enforced in |
|---|---|---|
| I1 | <Negative boundary or non-negotiable rule> | `<module_path>` |
| I2 | <Security, auth, or isolation invariant> | `<module_path>` |
| I3 | <Data consistency or transaction invariant> | `<module_path>` |

## 4. State & Persistence Models
- Schemas, vector indexes, Redis keys, or SQL tables.

## 5. Error Map
| Failure Case | Internal Handling | Client-Visible Result |
|---|---|---|
| ... | ... | ... |
```

---

### Step 5: Create `docs/requirements.md`
```markdown
# Requirements

This file tracks **behavior obligations** and the **formal change protocol**.

## Requirement Register

| ID | Requirement | Source of Truth | Tests | Status |
|---|---|---|---|---|
| R1 | <Core requirement> | `<module_path>` | `<test_path>` | done |
| R2 | <Core requirement> | `<module_path>` | `<test_path>` | done |

## Out of Scope
Explicitly list what the system does NOT do (prevents AI agent hallucination/scope creep):
- <Out of scope item 1>
- <Out of scope item 2>

## Change Protocol
1. Update or append the row in the register above.
2. If state models, flows, or invariants change, update `docs/architecture.md`.
3. If public APIs or contracts change, update relevant API specs and tests.
4. Run `make docs-check`.
5. Commit code and doc changes together in the same commit.
```

---

### Step 6: Create `docs/decisions.md`
```markdown
# Architectural Decisions & Rationale Index

Decisions recorded here represent binding constraints. Full ADRs (`docs/adr/NNNN-*.md`) are created only when a decision is hard to reverse, surprising, and involves a major trade-off.

## Decision Index

| Decision | Status | Rationale / Context | Consequence / Trade-off |
|---|---|---|---|
| Baseline Framework | Accepted | Initial project setup | ... |
| Storage / Database Selection | Accepted | Schema & scale requirements | ... |
| LLM / Embedding Choice | Accepted | Model capabilities vs cost | ... |
```

---

### Step 7: Install `scripts/check_docs.py`
Place this script in `scripts/check_docs.py` inside the target repository:

```python
"""Fail loudly when agent context docs disagree with code."""

import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DOC = "AGENTS.md"
ARCHITECTURE_DOC = "docs/architecture.md"
LINTED_DOCS = (AGENTS_DOC, ARCHITECTURE_DOC, "docs/requirements.md", "docs/decisions.md")

PATH_TOKEN = re.compile(r"(?<![\w/.:-])((?:app|src|api|tests|scripts|docs)/[^\s`'\"()\[\],;:|#]*)")
PLACEHOLDER = re.compile(r"[<>*{}]|NNNN")
VERIFIED_SHA = re.compile(r"Verified against\W*([0-9a-f]{7,40})\b")

def referenced_paths(text: str) -> set[str]:
    paths = set()
    for token in PATH_TOKEN.findall(text):
        if PLACEHOLDER.search(token):
            continue
        token = token.rstrip("./")
        if "/" in token:
            paths.add(token)
    return paths

def missing_paths(paths: Iterable[str], tracked: set[str]) -> list[str]:
    def present(path: str) -> bool:
        return path in tracked or any(item.startswith(path + "/") for item in tracked)
    return sorted(path for path in paths if not present(path))

def missing_module_rows(modules: Iterable[str], agents_text: str) -> list[str]:
    return [module for module in modules if module not in agents_text]

def python_modules(root: Path) -> list[str]:
    modules = []
    # Inspect all candidate source directories
    for src_dir in ("app", "src", "api"):
        d = root / src_dir
        if d.is_dir():
            for p in d.rglob("*.py"):
                if p.name != "__init__.py" and "__pycache__" not in p.parts:
                    modules.append(p.relative_to(root).as_posix())
    return sorted(modules)

def verified_sha(text: str) -> str | None:
    match = VERIFIED_SHA.search(text)
    return match.group(1) if match else None

def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    except OSError:
        return None

def tracked_files(root: Path) -> set[str]:
    result = _git(root, "ls-files")
    if result is not None and result.returncode == 0:
        return set(result.stdout.splitlines())
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}

def sha_problem(root: Path, sha: str) -> str | None:
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow is None or shallow.returncode != 0:
        return None
    if shallow.stdout.strip() == "true":
        return None
    resolved = _git(root, "cat-file", "-e", f"{sha}^{{commit}}")
    if resolved is None or resolved.returncode != 0:
        return f"verified-against SHA {sha} does not resolve to a commit"
    return None

def main(root: Path = ROOT) -> int:
    failures: list[str] = []
    texts: dict[str, str] = {}
    for doc in LINTED_DOCS:
        path = root / doc
        if not path.is_file():
            failures.append(f"{doc}: file is missing")
            continue
        texts[doc] = path.read_text(encoding="utf-8")

    tracked = tracked_files(root)
    for doc, text in texts.items():
        failures += [f"{doc}: referenced path is not tracked: {p}" for p in missing_paths(referenced_paths(text), tracked)]

    if AGENTS_DOC in texts:
        failures += [
            f"{AGENTS_DOC}: module has no map row: {m}"
            for m in missing_module_rows(python_modules(root), texts[AGENTS_DOC])
        ]

    if ARCHITECTURE_DOC in texts:
        sha = verified_sha(texts[ARCHITECTURE_DOC])
        if sha is None:
            failures.append(f"{ARCHITECTURE_DOC}: missing 'Verified against <sha>' stamp")
        elif problem := sha_problem(root, sha):
            failures.append(f"{ARCHITECTURE_DOC}: {problem}")

    if failures:
        print("docs disagree with code:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("docs agree with code")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

---

### Step 8: Wire Makefile and CI
1. **Makefile:** Add:
```makefile
docs-check:
	python scripts/check_docs.py
```
And add `docs-check` to `.PHONY` and `make help`.

2. **GitHub Actions (`.github/workflows/*.yml`):**
Add a check step right after linting:
```yaml
- name: Verify Documentation Consistency
  run: python scripts/check_docs.py
```

---

### Step 9: Verify and Commit
1. Run `python scripts/check_docs.py`. Ensure it outputs `docs agree with code` and returns code 0.
2. Commit with Conventional Commits:
```bash
git add AGENTS.md CLAUDE.md GEMINI.md docs/ scripts/check_docs.py Makefile .github/
git commit -m "docs(context): implement agent context pack and drift checker"
```

---

## QUALITY BAR (CRITICAL)
- **Do not invent fake modules:** The module map in `AGENTS.md` must strictly contain files that exist on disk.
- **Literal paths only:** Do not use `app/{a,b}.py`. The checker requires literal matches.
- **Invariants must be testable:** "System is fast" is invalid. "Vector queries partition by tenant_id" is valid.
```
