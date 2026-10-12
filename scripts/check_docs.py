"""Fail loudly when the agent context docs disagree with the code.

Stdlib only, no network. Run: ``uv run python scripts/check_docs.py``.
"""

import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS_DOC = "AGENTS.md"
ARCHITECTURE_DOC = "docs/architecture.md"
LINTED_DOCS = (AGENTS_DOC, ARCHITECTURE_DOC, "docs/requirements.md", "docs/decisions.md")

PATH_TOKEN = re.compile(r"(?<![\w/.:-])((?:app|tests|scripts|Learning|docs)/[^\s`'\"()\[\],;:|#]*)")
PLACEHOLDER = re.compile(r"[<>*{}]|NNNN")
KEY_PREFIX = re.compile(r"wrapper:[a-z-]+(?::[a-z-]+)*:")
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


def key_prefixes(text: str) -> set[str]:
    return set(KEY_PREFIX.findall(text))


def key_prefix_drift(code: set[str], documented: set[str]) -> list[str]:
    return [f"Redis key prefix in code but not documented: {key}" for key in sorted(code - documented)] + [
        f"Redis key prefix documented but not in code: {key}" for key in sorted(documented - code)
    ]


def missing_module_rows(modules: Iterable[str], agents_text: str) -> list[str]:
    return [module for module in modules if module not in agents_text]


def python_modules(root: Path) -> list[str]:
    return sorted(
        path.relative_to(root).as_posix()
        for path in (root / "app").rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


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
        print(f"notice: git unavailable; skipped verified-against SHA check for {sha}")
        return None
    if shallow.stdout.strip() == "true":
        print(f"notice: shallow clone; skipped verified-against SHA check for {sha}")
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
        failures += [f"{doc}: referenced path is not tracked: {path}" for path in missing_paths(referenced_paths(text), tracked)]

    if AGENTS_DOC in texts:
        failures += [
            f"{AGENTS_DOC}: module has no map row: {module}"
            for module in missing_module_rows(python_modules(root), texts[AGENTS_DOC])
        ]

    if ARCHITECTURE_DOC in texts:
        code = set().union(*(key_prefixes(p.read_text(encoding="utf-8")) for p in (root / "app").rglob("*.py")))
        failures += [f"{ARCHITECTURE_DOC}: {item}" for item in key_prefix_drift(code, key_prefixes(texts[ARCHITECTURE_DOC]))]
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
