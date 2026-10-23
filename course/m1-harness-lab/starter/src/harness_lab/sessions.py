from collections.abc import Callable
from pathlib import Path
from typing import Self


class TicketSessions:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def lookup(self, ticket_id: str) -> str | None:
        raise NotImplementedError

    def total_cost(self, ticket_id: str) -> float:
        raise NotImplementedError

    def remember(
        self, ticket_id: str, session_id: str, status: str = "open", cost_usd: float = 0.0
    ) -> None:
        raise NotImplementedError

    def forget(self, ticket_id: str) -> None:
        raise NotImplementedError

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        raise NotImplementedError


async def resume_or_fresh(options, query_fn: Callable, prompt: str) -> tuple[list, bool]:
    raise NotImplementedError
