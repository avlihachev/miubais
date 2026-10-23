from dataclasses import dataclass

from harness_lab.types import Summary


@dataclass(frozen=True)
class Caps:
    max_turns: int
    max_usd: float


def summarise(messages: list, caps: Caps, *, previous_cost_usd: float = 0.0) -> Summary:
    raise NotImplementedError


def to_markdown(summary: Summary) -> str:
    raise NotImplementedError
