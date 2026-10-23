from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from injection_lab.provenance import Taint
from injection_lab.types import AuditEvent

GENESIS = "0" * 64


class AuditError(ValueError):
    pass


@dataclass(frozen=True)
class Verification:
    ok: bool
    line: int | None
    reason: str


@dataclass(frozen=True)
class CheckItem:
    item: str
    satisfied_by: str
    ok: bool


def digest(record: dict) -> str:
    raise NotImplementedError


class AuditLog:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def append(self, event: AuditEvent) -> str:
        raise NotImplementedError

    def record(
        self,
        event: str,
        *,
        actor: str,
        payload: dict | None = None,
        tool_use_id: str | None = None,
        run_id: str | None = None,
        ticket_id: str | None = None,
    ) -> str:
        raise NotImplementedError


def verify(path: Path, *, head: str | None = None) -> Verification:
    raise NotImplementedError


def observer(log: AuditLog, run_id: str, ticket_id: str) -> Callable[[Any], None]:
    raise NotImplementedError


def on_denied(
    log: AuditLog, *, run_id: str | None = None, ticket_id: str | None = None
) -> Callable[[dict], None]:
    raise NotImplementedError


def watch_taint(log: AuditLog, taint: Taint, *, approver: str = "human") -> Taint:
    raise NotImplementedError


def checklist(path_to_log: Path, *, head: str | None = None) -> list[CheckItem]:
    raise NotImplementedError
