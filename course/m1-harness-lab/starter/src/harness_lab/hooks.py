from collections.abc import Callable

from harness_lab.policy import Guard


def guard_hook(guard: Guard, rewrite: dict[str, str] | None = None) -> Callable:
    raise NotImplementedError
