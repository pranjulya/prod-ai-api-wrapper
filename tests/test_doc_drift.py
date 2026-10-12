import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_checker():
    spec = importlib.util.spec_from_file_location("check_docs", ROOT / "scripts" / "check_docs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_docs = load_checker()


def test_referenced_paths_extracts_repo_tokens_and_strips_punctuation():
    text = "See `app/main.py`, then app/services/jobs.py::update_job and tests/conftest.py. Also docs/plans/."
    assert check_docs.referenced_paths(text) == {
        "app/main.py",
        "app/services/jobs.py",
        "tests/conftest.py",
        "docs/plans",
    }


def test_referenced_paths_skips_placeholders_and_urls():
    text = (
        "docs/superpowers/specs/<date>-phase-N-*-design.md app/**/*.py docs/adr/NNNN-*.md "
        "app/api/{health,responses}.py https://github.com/org/repo/docs/x.md"
    )
    assert check_docs.referenced_paths(text) == set()


def test_missing_paths_accepts_tracked_files_and_their_directories():
    tracked = {"app/main.py", "docs/plans/agent-context-pack.md"}
    assert check_docs.missing_paths({"app/main.py", "docs/plans", "app"}, tracked) == []
    assert check_docs.missing_paths({"lessons/intro.html", "app/gone.py"}, tracked) == [
        "app/gone.py",
        "lessons/intro.html",
    ]


def test_key_prefixes_handle_hyphens_multi_segment_and_fstrings():
    source = '\n'.join(
        [
            'f"wrapper:job:{job_id}"',
            'f"wrapper:openai-response-job:{digest}"',
            'KEY = "wrapper:webhook:event:" + event_id',
            'f"wrapper:job-reconciliation:{job_id}"',
            "every key `wrapper:*`",
        ]
    )
    assert check_docs.key_prefixes(source) == {
        "wrapper:job:",
        "wrapper:openai-response-job:",
        "wrapper:webhook:event:",
        "wrapper:job-reconciliation:",
    }


def test_key_prefix_drift_reports_both_directions():
    assert check_docs.key_prefix_drift({"wrapper:a:", "wrapper:b:"}, {"wrapper:b:", "wrapper:c:"}) == [
        "Redis key prefix in code but not documented: wrapper:a:",
        "Redis key prefix documented but not in code: wrapper:c:",
    ]


def test_missing_module_rows_requires_literal_paths():
    modules = ["app/api/health.py", "app/api/responses.py"]
    assert check_docs.missing_module_rows(modules, "| `app/api/{health,responses}.py` |") == modules
    assert check_docs.missing_module_rows(modules, "`app/api/health.py`\n`app/api/responses.py`") == []


def test_python_modules_excludes_init_files(tmp_path):
    (tmp_path / "app" / "api").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "app" / "main.py").write_text("")
    (tmp_path / "app" / "api" / "health.py").write_text("")
    assert check_docs.python_modules(tmp_path) == ["app/api/health.py", "app/main.py"]


def test_verified_sha_parses_stamp():
    assert check_docs.verified_sha("> Verified against `3eef939` (2026-10-13).") == "3eef939"
    assert check_docs.verified_sha("no stamp here") is None


def test_sha_check_skips_shallow_and_missing_git(tmp_path):
    assert check_docs.sha_problem(tmp_path, "deadbee") is None
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert check_docs.sha_problem(tmp_path, "deadbee") == "verified-against SHA deadbee does not resolve to a commit"


def test_main_reports_failures_for_missing_docs(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text('KEY = "wrapper:job:"\n')
    assert check_docs.main(tmp_path) == 1
    out = capsys.readouterr().out
    assert "AGENTS.md: file is missing" in out


def test_real_tree_docs_agree_with_code():
    assert check_docs.main(ROOT) == 0
