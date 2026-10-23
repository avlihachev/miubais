from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Item:
    id: str
    prompt: str


@dataclass(frozen=True)
class Outcome:
    kind: Literal["succeeded", "errored", "canceled", "expired", "unknown"]
    text: str | None
    error_type: str | None
    retryable: bool


def build_batch(
    items: Iterable[Item], *, model: str, max_tokens: int, system: list | str | None = None
) -> list[dict]:
    raise NotImplementedError


def join_results(items: Iterable[Item], results: Iterable) -> dict[str, Outcome]:
    raise NotImplementedError
