import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Self

from harnesskit.sessions import now

SCHEMA = "CREATE TABLE IF NOT EXISTS ops (key TEXT PRIMARY KEY, result TEXT, at TEXT)"


class IdempotencyStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute(SCHEMA)
        self.db.commit()

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT result FROM ops WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, result: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO ops (key, result, at) VALUES (?, ?, ?)", (key, result, now())
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def once(store: IdempotencyStore, key: str, fn: Callable[[], str]) -> str:
    stored = store.get(key)
    if stored is not None:
        return stored
    store.put(key, fn())
    # another writer may have won the insert; its result is the one of record
    return store.get(key)
