import asyncio
import sqlite3
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from conftest import assistant, recorder, result, text
from harness_lab.sessions import TicketSessions, resume_or_fresh


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "sessions.db"


def test_round_trip(db):
    with TicketSessions(db) as sessions:
        assert sessions.lookup("T-1") is None
        sessions.remember("T-1", "sess-a")
        assert sessions.lookup("T-1") == "sess-a"


def test_remember_replaces(db):
    with TicketSessions(db) as sessions:
        sessions.remember("T-1", "sess-a")
        sessions.remember("T-1", "sess-b")
        assert sessions.lookup("T-1") == "sess-b"


def test_survives_reopen(db):
    with TicketSessions(db) as sessions:
        sessions.remember("T-1", "sess-a")
    with TicketSessions(db) as sessions:
        assert sessions.lookup("T-1") == "sess-a"


def test_forget(db):
    with TicketSessions(db) as sessions:
        sessions.remember("T-1", "sess-a")
        sessions.remember("T-2", "sess-b")
        sessions.forget("T-1")
        assert sessions.lookup("T-1") is None
        assert sessions.lookup("T-2") == "sess-b"


def test_row_shape(db):
    with TicketSessions(db) as sessions:
        sessions.remember("T-1", "sess-a")
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT ticket_id, session_id, status, updated_at, cost_usd FROM sessions"
        ).fetchone()
    assert row[:3] == ("T-1", "sess-a", "open")
    assert row[3]
    assert row[4] == 0.0


def test_total_cost_round_trip(db):
    with TicketSessions(db) as sessions:
        assert sessions.total_cost("T-1") == 0.0
        sessions.remember("T-1", "sess-a", "open", cost_usd=0.42)
    with TicketSessions(db) as sessions:
        assert sessions.total_cost("T-1") == 0.42
        sessions.remember("T-1", "sess-a", "done", cost_usd=0.61)
        assert sessions.total_cost("T-1") == 0.61


def test_adds_cost_column_to_an_older_table(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE sessions (ticket_id TEXT PRIMARY KEY, session_id TEXT, "
            "status TEXT, updated_at TEXT)"
        )
        conn.execute("INSERT INTO sessions VALUES ('T-1', 'sess-a', 'open', '2026-10-01')")
    with TicketSessions(db) as sessions:
        assert sessions.lookup("T-1") == "sess-a"
        assert sessions.total_cost("T-1") == 0.0
        sessions.remember("T-2", "sess-b", cost_usd=0.25)
        assert sessions.total_cost("T-2") == 0.25


def run(options, query_fn):
    return asyncio.run(resume_or_fresh(options, query_fn, "continue"))


def resumes(calls):
    return [options.resume for _, options in calls]


GOOD = [assistant(text("done")), result(session_id="fresh")]


def test_resume_raises_falls_back_to_fresh():
    query_fn, calls = recorder(RuntimeError("No conversation found"), GOOD)
    messages, resumed = run(ClaudeAgentOptions(resume="stale"), query_fn)
    assert resumes(calls) == ["stale", None]
    assert resumed is False
    assert messages == GOOD


def test_resume_error_result_before_assistant_falls_back():
    query_fn, calls = recorder([result("error_during_execution")], GOOD)
    messages, resumed = run(ClaudeAgentOptions(resume="stale"), query_fn)
    assert resumes(calls) == ["stale", None]
    assert (messages, resumed) == (GOOD, False)


def test_successful_resume_keeps_session():
    query_fn, calls = recorder(GOOD)
    messages, resumed = run(ClaudeAgentOptions(resume="live"), query_fn)
    assert resumes(calls) == ["live"]
    assert (messages, resumed) == (GOOD, True)


def test_error_after_assistant_output_is_not_retried():
    partial = [assistant(text("working")), result("error_max_turns")]
    query_fn, calls = recorder(partial)
    messages, resumed = run(ClaudeAgentOptions(resume="live"), query_fn)
    assert resumes(calls) == ["live"]
    assert (messages, resumed) == (partial, True)


def test_no_resume_means_no_retry():
    query_fn, calls = recorder([result("error_max_turns")])
    messages, resumed = run(ClaudeAgentOptions(), query_fn)
    assert resumes(calls) == [None]
    assert resumed is False
    assert messages[0].subtype == "error_max_turns"


def test_fresh_budget_stop_returns_its_messages():
    stopped = [assistant(text("reading")), result("error_max_budget_usd", cost=0.6)]
    query_fn, _ = recorder(stopped)
    assert run(ClaudeAgentOptions(), query_fn) == (stopped, False)


def test_fresh_failure_propagates():
    query_fn, calls = recorder(RuntimeError("stale"), RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        run(ClaudeAgentOptions(resume="stale"), query_fn)
    assert resumes(calls) == ["stale", None]


def test_failure_after_output_without_a_result_propagates():
    query_fn, calls = recorder([assistant(text("working")), RuntimeError("connection lost")])
    with pytest.raises(RuntimeError, match="connection lost"):
        run(ClaudeAgentOptions(resume="live"), query_fn)
    assert resumes(calls) == ["live"]


def test_prompt_is_passed_to_every_attempt():
    query_fn, calls = recorder(RuntimeError("stale"), GOOD)
    asyncio.run(resume_or_fresh(ClaudeAgentOptions(resume="stale"), query_fn, "Ticket 001"))
    assert [prompt for prompt, _ in calls] == ["Ticket 001", "Ticket 001"]
