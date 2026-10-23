from collections.abc import Callable

import anthropic

from cost_lab.loop import TruncatedError

__all__ = ["TruncatedError", "stream_final"]


def stream_final(
    client: anthropic.Anthropic,
    *,
    on_text: Callable[[str], None] | None = None,
    **params,
) -> anthropic.types.Message:
    raise NotImplementedError
