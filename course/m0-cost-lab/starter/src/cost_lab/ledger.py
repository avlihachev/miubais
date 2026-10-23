from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Entry:
    label: str
    model: str
    prompt_tokens: int
    cache_read_tokens: int
    output_tokens: int
    usd: float


def load_prices(path: Path | None = None) -> dict:
    """Return the price table in path, or the packaged prices.json when path is None."""
    raise NotImplementedError


def cost_usd(
    usage,
    model: str,
    prices: dict,
    *,
    ttl: Literal["5m", "1h"] | None = None,
    batch: bool | None = None,
) -> float:
    """Return the USD cost of usage; ttl and batch, when given, override what usage reports."""
    raise NotImplementedError


class Ledger:
    def __init__(self, prices: dict):
        self.prices = prices
        self.entries: list[Entry] = []

    def add(self, label: str, usage, model: str, **kw) -> Entry:
        """Return the Entry recorded for this call."""
        raise NotImplementedError

    def total(self) -> float:
        raise NotImplementedError

    def by_label(self) -> dict[str, float]:
        raise NotImplementedError

    def cache_hit_ratio(self) -> float:
        raise NotImplementedError

    def to_markdown(self) -> str:
        raise NotImplementedError
