from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CacheReport:
    total_prompt: int
    read: int
    written: int
    uncached: int
    hit_ratio: float


def build_request(
    *,
    model: str,
    max_tokens: int,
    system_static: str,
    tools: list[dict],
    history: list[dict],
    user_turn: str,
    ttl: Literal["5m", "1h"] = "5m",
) -> dict:
    raise NotImplementedError


def prefix_bytes(params: dict) -> bytes:
    """Return the compact JSON of params' model, tools and system, in that order, keys as sent."""
    raise NotImplementedError


def cache_report(usage) -> CacheReport:
    raise NotImplementedError
