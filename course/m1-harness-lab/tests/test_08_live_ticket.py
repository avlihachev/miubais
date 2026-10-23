import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from claude_agent_sdk import HookMatcher, UserMessage, query
from conftest import assistant, recorder, result, text, tool_use
from harness_lab.caps import Caps, to_markdown
from harness_lab.policy import Guard
from harness_lab.runner import run_ticket
from harness_lab.sessions import TicketSessions
from harnesskit.testing import result_error

REPO_ROOT = Path(__file__).resolve().parents[3]
TINYSHOP = REPO_ROOT / "fixtures" / "tinyshop"
TICKET = "tickets/001-discount-rounding.md"
TICKET_TEST = "tests/test_pricing.py::test_discount_rounds_half_up"
BLOCKED = [
    r"\brm\s+(?:[^\s;&|]+\s+)*?(?:-[a-z]*r[a-z]*|--recursive)\b",
    r"\bgit(?:\s+(?:-c\s+\S+|--(?:git-dir|work-tree|namespace)\s+\S+|--?[\w-]+(?:=\S+)?))*\s+push\b",
    r"\bsudo\b",
    r"\b(curl|wget)\b.*\|\s*(ba|z)?sh\b",
]


def logged_in() -> bool:
    try:
        from miubais.model import claude_available
    except ImportError:
        proc = subprocess.run(
            ["claude", "auth", "status"], check=False, capture_output=True, text=True
        )
        return proc.returncode == 0 and '"loggedIn": true' in proc.stdout
    return claude_available()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def shop(tmp_path) -> Path:
    repo = tmp_path / "tinyshop"
    shutil.copytree(TINYSHOP, repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=lab", "-c", "user.email=lab@example.com", "commit", "-qm", "base")
    return repo


def pytest_in(repo: Path, *args: str) -> int:
    proc = subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "--frozen", "pytest", "-q", *args],
        check=False,
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo / "src")},
        capture_output=True,
        text=True,
    )
    print(proc.stdout[-400:])
    return proc.returncode


def test_runner_options_and_session_are_wired(shop, tmp_path):
    messages = [
        assistant(text("reading"), tool_use("t1", "Read", {"file_path": TICKET})),
        UserMessage(content="ok"),
        assistant(text("fixed the rounding")),
        result("success", turns=2, cost=0.05, session_id="sess-new"),
    ]
    query_fn, calls = recorder(messages)
    with TicketSessions(tmp_path / "s.db") as sessions:
        sessions.remember("001-discount-rounding", "sess-old")
        summary = run_ticket(
            shop / TICKET,
            shop,
            guard=Guard([shop / "src"], BLOCKED),
            sessions=sessions,
            caps=Caps(max_turns=7, max_usd=0.4),
            query_fn=query_fn,
        )
        assert sessions.lookup("001-discount-rounding") == "sess-new"
    assert summary.stopped_by == "success"
    assert summary.final_text == "fixed the rounding"
    prompt, options = calls[0]
    assert "Discounted totals round half-cents down" in prompt
    assert options.resume == "sess-old"
    assert Path(options.cwd) == shop
    assert options.max_turns == 7 and options.max_budget_usd == 0.4
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []
    assert set(options.allowed_tools) == {"Read", "Grep", "Glob", "Edit", "Write", "Bash"}
    matchers = options.hooks["PreToolUse"]
    assert matchers and all(isinstance(m, HookMatcher) and m.hooks for m in matchers)


FORBIDDEN = [
    ("Write", {"file_path": "tests/x.py", "content": "x = 1\n"}),
    ("Bash", {"command": "git push origin main"}),
]


def hooks_for(options, tool: str) -> list:
    return [
        hook
        for matcher in options.hooks.get("PreToolUse", [])
        if matcher.matcher in (None, "", "*") or re.fullmatch(matcher.matcher, tool)
        for hook in matcher.hooks
    ]


@pytest.mark.parametrize(("tool", "tool_input"), FORBIDDEN, ids=["write-tests", "git-push"])
def test_registered_hooks_deny_forbidden_calls(shop, tmp_path, tool, tool_input):
    query_fn, calls = recorder([assistant(text("done")), result("success")])
    with TicketSessions(tmp_path / "s.db") as sessions:
        run_ticket(
            shop / TICKET,
            shop,
            guard=Guard([shop / "src"], BLOCKED),
            sessions=sessions,
            caps=Caps(max_turns=3, max_usd=0.1),
            query_fn=query_fn,
        )
    hooks = hooks_for(calls[0][1], tool)
    assert hooks, f"no PreToolUse hook would see a {tool} call"
    event = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-1",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": str(shop),
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_1",
    }
    for hook in hooks:
        out = asyncio.run(hook(event, "toolu_1", {"signal": None}))
        assert set(out) == {"hookSpecificOutput"}, out
        specific = out["hookSpecificOutput"]
        assert set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
        assert specific["hookEventName"] == "PreToolUse"
        assert specific["permissionDecision"] == "deny"
        assert isinstance(specific["permissionDecisionReason"], str)
        assert specific["permissionDecisionReason"]


def test_runner_starts_fresh_without_a_stored_session(shop, tmp_path):
    query_fn, calls = recorder([assistant(text("done")), result("success", session_id="sess-1")])
    with TicketSessions(tmp_path / "s.db") as sessions:
        run_ticket(
            shop / TICKET,
            shop,
            guard=Guard([shop / "src"], BLOCKED),
            sessions=sessions,
            caps=Caps(max_turns=3, max_usd=0.1),
            query_fn=query_fn,
        )
        assert sessions.lookup("001-discount-rounding") == "sess-1"
    assert calls[0][1].resume is None


def run_offline(shop, tmp_path, *runs, stored=None, stored_cost=0.0):
    query_fn, calls = recorder(*runs)
    with TicketSessions(tmp_path / "s.db") as sessions:
        if stored:
            sessions.remember("001-discount-rounding", stored, cost_usd=stored_cost)
        summary = run_ticket(
            shop / TICKET,
            shop,
            guard=Guard([shop / "src"], BLOCKED),
            sessions=sessions,
            caps=Caps(max_turns=12, max_usd=0.5),
            query_fn=query_fn,
        )
        after = (
            sessions.lookup("001-discount-rounding"),
            sessions.total_cost("001-discount-rounding"),
        )
    return summary, calls, after


def test_fresh_budget_stop_is_reported_without_raising(shop, tmp_path):
    run = [assistant(text("reading")), result("error_max_budget_usd", cost=0.52, session_id="s2")]
    summary, calls, after = run_offline(shop, tmp_path, run)
    assert (summary.stopped_by, len(calls), after) == ("budget", 1, ("s2", 0.52))


def test_resumed_max_turns_after_output_is_not_rerun(shop, tmp_path):
    run = [assistant(text("working")), result("error_max_turns", turns=12, session_id="sess-old")]
    summary, calls, _ = run_offline(shop, tmp_path, run, stored="sess-old")
    assert [options.resume for _, options in calls] == ["sess-old"]
    assert summary.stopped_by == "max_turns"


def test_resumed_run_reports_its_own_spend_against_the_cap(shop, tmp_path):
    run = [assistant(text("finishing")), result("success", cost=0.70, session_id="sess-old")]
    summary, _, after = run_offline(shop, tmp_path, run, stored="sess-old", stored_cost=0.45)
    assert summary.stopped_by == "success"
    assert abs(summary.cost_usd - 0.25) < 1e-9
    assert after == ("sess-old", 0.70)


def test_fresh_fallback_does_not_subtract_the_stale_total(shop, tmp_path):
    stale = [result("error_during_execution", session_id="sess-old")]
    fresh = [assistant(text("again")), result("success", cost=0.30, session_id="sess-new")]
    summary, _, after = run_offline(
        shop, tmp_path, stale, fresh, stored="sess-old", stored_cost=0.45
    )
    assert (summary.stopped_by, after) == ("success", ("sess-new", 0.30))
    assert abs(summary.cost_usd - 0.30) < 1e-9


def test_stale_session_is_replaced_through_the_runner(shop, tmp_path):
    missing = "No conversation found with session ID: sess-old"
    stale = result_error(result("error_during_execution", session_id="sess-old", errors=[missing]))
    fresh = [assistant(text("starting over")), result("success", session_id="sess-new")]
    summary, calls, after = run_offline(shop, tmp_path, stale, fresh, stored="sess-old")
    assert [options.resume for _, options in calls] == ["sess-old", None]
    assert summary.stopped_by == "success"
    assert after[0] == "sess-new"


def test_error_during_execution_is_error(shop, tmp_path):
    run = [assistant(text("x")), result("error_during_execution", session_id="s3")]
    summary, _, _ = run_offline(shop, tmp_path, run)
    assert summary.stopped_by == "error"


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not logged_in(), reason="needs claude-auth")
def test_live_ticket_001(shop, tmp_path):
    seen = []

    def spy(prompt=None, options=None):
        seen.append(options)
        return query(prompt=prompt, options=options)

    with TicketSessions(tmp_path / "s.db") as sessions:
        summary = run_ticket(
            shop / TICKET,
            shop,
            guard=Guard([shop / "src"], BLOCKED),
            sessions=sessions,
            caps=Caps(max_turns=12, max_usd=0.75),
            query_fn=spy,
        )
    assert seen and seen[0].hooks and seen[0].hooks.get("PreToolUse"), "no PreToolUse hooks"
    print(to_markdown(summary))
    changed = [line[3:] for line in git(shop, "status", "--porcelain").splitlines()]
    print("files_changed:", changed)
    assert summary.stopped_by == "success", to_markdown(summary)
    assert pytest_in(shop, "--runxfail", TICKET_TEST) == 0
    assert pytest_in(shop, "--deselect", TICKET_TEST) == 0
    assert changed and all(path.startswith("src/") for path in changed), changed
