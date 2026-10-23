from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from harnesskit.hooks import HookCallback

from injection_lab import types
from injection_lab.types import Detection, Tagged

DENY_REASON = "untrusted content in context: approval required"
ERROR_REASON = "detector error"


class ApprovalError(PermissionError):
    pass


@dataclass
class Taint(types.Taint):
    on_mark: Callable[["Taint"], None] | None = field(default=None, repr=False, compare=False)
    on_clear: Callable[["Taint"], None] | None = field(default=None, repr=False, compare=False)
    _approval_id: str | None = field(default=None, init=False, repr=False, compare=False)

    def mark(
        self, detection: Detection, tool_use_id: str | None, *, reason: str | None = None
    ) -> None:
        raise NotImplementedError

    def mint_approval(self) -> str | None:
        raise NotImplementedError

    def clear(self, approval_id: str) -> None:
        raise NotImplementedError


def wrap(tool_name: str, tool_input: dict, output: str) -> Tagged:
    raise NotImplementedError


def map_strings(value: Any, fn: Callable[[str], str], *, keys: frozenset[str] | None = None) -> Any:
    raise NotImplementedError


def compose(*callbacks: HookCallback) -> HookCallback:
    raise NotImplementedError


def taint_policy(
    taint: Taint,
    *,
    readonly_allow: frozenset[str],
    audit: Callable[[dict], None] | None = None,
) -> HookCallback:
    raise NotImplementedError


def post_hook(
    taint: Taint,
    detector: Callable[..., Detection],
    *,
    scrub: Callable[[str], str] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> HookCallback:
    raise NotImplementedError
