import sqlite3

from harnesskit.idempotent import IdempotencyStore, once


def counter():
    calls = []

    def fn() -> str:
        calls.append(1)
        return f"result-{len(calls)}"

    return fn, calls


def test_once_runs_once(tmp_path):
    fn, calls = counter()
    with IdempotencyStore(tmp_path / "ops.db") as store:
        assert once(store, "k", fn) == "result-1"
        assert once(store, "k", fn) == "result-1"
    assert len(calls) == 1


def test_distinct_keys_run_separately(tmp_path):
    fn, calls = counter()
    with IdempotencyStore(tmp_path / "ops.db") as store:
        assert once(store, "a", fn) == "result-1"
        assert once(store, "b", fn) == "result-2"
    assert len(calls) == 2


def test_once_across_reopen(tmp_path):
    path = tmp_path / "ops.db"
    fn, calls = counter()
    store = IdempotencyStore(path)
    once(store, "k", fn)
    store.close()
    with IdempotencyStore(path) as again:
        assert once(again, "k", fn) == "result-1"
    assert len(calls) == 1


def test_failure_is_not_recorded(tmp_path):
    def broken() -> str:
        raise RuntimeError("down")

    fn, _ = counter()
    with IdempotencyStore(tmp_path / "ops.db") as store:
        try:
            once(store, "k", broken)
        except RuntimeError:
            pass
        assert once(store, "k", fn) == "result-1"


def test_first_writer_wins(tmp_path):
    with IdempotencyStore(tmp_path / "ops.db") as store:
        store.put("k", "first")
        store.put("k", "second")
        assert store.get("k") == "first"


def test_schema(tmp_path):
    path = tmp_path / "ops.db"
    IdempotencyStore(path).close()
    with sqlite3.connect(path) as db:
        cols = [row[1] for row in db.execute("PRAGMA table_info(ops)")]
    assert cols == ["key", "result", "at"]
