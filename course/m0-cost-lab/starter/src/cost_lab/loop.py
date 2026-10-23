from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True)
class LoopResult:
    final_text: str
    turns: int
    usage: UsageTotals


class TruncatedError(RuntimeError):
    def __init__(self, partial_text: str):
        super().__init__("response truncated at max_tokens")
        self.partial_text = partial_text


class RefusalError(RuntimeError):
    def __init__(self, category: str | None):
        super().__init__(f"model refused ({category or 'no category'})")
        self.category = category


def run_tool_loop(
    client,
    *,
    model: str,
    max_tokens: int,
    system: str | list,
    tools: list[dict],
    messages: list[dict],
    execute: Callable[[str, dict], str],
    max_turns: int = 10,
) -> LoopResult:
    """Return the final text, the number of model calls, and their summed usage."""
    raise NotImplementedError
