import multiprocessing
import sqlite3
from pathlib import Path

import pytest
from harness_lab.idempotent import Once


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "ops.db"


def test_runs_once_and_returns_stored_result(db):
    calls = []

    def send():
        calls.append(1)
        return f"sent-{len(calls)}"

    once = Once(db)
    assert once.run("email:1", send) == "sent-1"
    assert once.run("email:1", send) == "sent-1"
    assert len(calls) == 1


def test_different_keys_both_run(db):
    once = Once(db)
    assert once.run("a", lambda: "A") == "A"
    assert once.run("b", lambda: "B") == "B"


def test_executes_once_across_reopen(db):
    calls = []

    def refund():
        calls.append(1)
        return "refund-42"

    assert Once(db).run("refund:42", refund) == "refund-42"
    assert Once(db).run("refund:42", refund) == "refund-42"
    assert len(calls) == 1


def test_preinserted_row_wins_without_running_fn(db):
    Once(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO ops VALUES (?, ?, ?)", ("k", "earlier", "2026-01-01T00:00:00+00:00")
        )
    calls = []
    assert Once(db).run("k", lambda: calls.append(1) or "later") == "earlier"
    assert calls == []


def test_failing_fn_is_not_recorded(db):
    once = Once(db)

    def boom():
        raise RuntimeError("gateway down")

    with pytest.raises(RuntimeError, match="gateway down"):
        once.run("k", boom)
    assert once.run("k", lambda: "ok") == "ok"


def test_row_shape(db):
    Once(db).run("k", lambda: "v")
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT key, result, at FROM ops").fetchone()
    assert row[:2] == ("k", "v")
    assert row[2]


def _worker(path, value, out):
    out.put(Once(Path(path)).run("shared", lambda: value))


def test_two_processes_agree_on_one_result(db):
    ctx = multiprocessing.get_context("spawn")
    out = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(str(db), v, out)) for v in ("one", "two")]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=30)
        assert proc.exitcode == 0
    results = {out.get(timeout=5), out.get(timeout=5)}
    assert len(results) == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ops").fetchone()[0] == 1
