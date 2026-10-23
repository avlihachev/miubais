import sqlite3

from harnesskit.sessions import SessionRecord, SessionStore


def test_missing_ticket_is_none(tmp_path):
    with SessionStore(tmp_path / "s.db") as store:
        assert store.get("001") is None


def test_round_trip(tmp_path):
    with SessionStore(tmp_path / "s.db") as store:
        store.put("001", "sess-a")
        record = store.get("001")
    assert isinstance(record, SessionRecord)
    assert (record.ticket_id, record.session_id, record.status) == ("001", "sess-a", "open")
    assert record.updated_at


def test_put_replaces_and_mark_updates(tmp_path):
    with SessionStore(tmp_path / "s.db") as store:
        store.put("001", "sess-a")
        store.put("001", "sess-b", status="running")
        assert store.get("001").session_id == "sess-b"
        store.mark("001", "done")
        assert store.get("001").status == "done"
        assert store.get("001").session_id == "sess-b"


def test_reopen_keeps_records(tmp_path):
    path = tmp_path / "s.db"
    store = SessionStore(path)
    store.put("002", "sess-x", status="done")
    store.close()
    with SessionStore(path) as again:
        assert again.get("002").session_id == "sess-x"
        assert again.get("002").status == "done"


def test_schema(tmp_path):
    path = tmp_path / "s.db"
    SessionStore(path).close()
    with sqlite3.connect(path) as db:
        cols = [row[1] for row in db.execute("PRAGMA table_info(tickets)")]
    assert cols == ["ticket_id", "session_id", "status", "updated_at", "cost_usd"]


def test_cost_round_trip(tmp_path):
    with SessionStore(tmp_path / "s.db") as store:
        store.put("001", "sess-a")
        assert store.get("001").cost_usd == 0.0
        store.put("001", "sess-a", cost_usd=0.42)
        assert store.get("001").cost_usd == 0.42
        store.mark("001", "done")
        assert store.get("001").cost_usd == 0.42


def test_old_database_gains_the_cost_column(tmp_path):
    path = tmp_path / "s.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, session_id TEXT, status TEXT, "
            "updated_at TEXT)"
        )
        db.execute("INSERT INTO tickets VALUES ('001', 'sess-a', 'open', 'then')")
    with SessionStore(path) as store:
        assert store.get("001").cost_usd == 0.0
