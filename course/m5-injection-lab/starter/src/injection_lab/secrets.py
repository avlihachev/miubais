from collections.abc import Callable

from harnesskit.hooks import HookCallback

from injection_lab.types import Redaction

ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM")


def scrub(text: str) -> Redaction:
    raise NotImplementedError


def subprocess_env(extra: dict | None = None) -> dict:
    raise NotImplementedError


def scrub_hook(
    *,
    on_redact: Callable[[dict[str, int]], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> HookCallback:
    raise NotImplementedError


def guard_env(options):
    raise NotImplementedError
