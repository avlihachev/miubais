from pathlib import Path
from typing import Any

from harnesskit.report import RunReport

from trace_lab.cost import Prices


class BudgetGuard:
    def __init__(self, limit_usd: float, prices: Prices) -> None:
        self.limit_usd = limit_usd
        self.prices = prices
        self.cost_usd = 0.0
        self.tripped = False
        self.messages_seen = 0

    def __call__(self, message: Any) -> bool:
        raise NotImplementedError


def run_with_budget(
    ticket_path: Path, repo: Path, *, limit_usd: float, prices: Prices, **run_ticket_kwargs: Any
) -> RunReport:
    raise NotImplementedError
