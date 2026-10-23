from collections.abc import Callable
from pathlib import Path

from harness_lab.caps import Caps
from harness_lab.policy import Guard
from harness_lab.sessions import TicketSessions
from harness_lab.types import Summary


def run_ticket(
    ticket_path: Path,
    repo: Path,
    *,
    guard: Guard,
    sessions: TicketSessions,
    caps: Caps,
    query_fn: Callable | None = None,
) -> Summary:
    raise NotImplementedError
