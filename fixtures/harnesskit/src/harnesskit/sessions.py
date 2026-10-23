import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    session_id TEXT,
    status TEXT,
    updated_at TEXT,
    cost_usd REAL NOT NULL DEFAULT 0
)
"""


@dataclass(frozen=True)
class SessionRecord:
    ticket_id: str
    session_id: str
    status: str
    updated_at: str
    cost_usd: float = 0.0


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SessionStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(tickets)")}
        if "cost_usd" not in columns:
            self.db.execute("ALTER TABLE tickets ADD COLUMN cost_usd REAL NOT NULL DEFAULT 0")
        self.db.commit()

    def get(self, ticket_id: str) -> SessionRecord | None:
        row = self.db.execute(
            "SELECT ticket_id, session_id, status, updated_at, cost_usd FROM tickets "
            "WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
        return SessionRecord(*row) if row else None

    def put(
        self, ticket_id: str, session_id: str, status: str = "open", cost_usd: float = 0.0
    ) -> None:
        self.db.execute(
            "INSERT INTO tickets (ticket_id, session_id, status, updated_at, cost_usd) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ticket_id) DO UPDATE SET session_id = excluded.session_id, "
            "status = excluded.status, updated_at = excluded.updated_at, "
            "cost_usd = excluded.cost_usd",
            (ticket_id, session_id, status, now(), cost_usd),
        )
        self.db.commit()

    def mark(self, ticket_id: str, status: str) -> None:
        self.db.execute(
            "UPDATE tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
            (status, now(), ticket_id),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
