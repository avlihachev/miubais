from collections.abc import Iterable
from pathlib import Path

from injection_lab.types import Item, RedTeamCase, RedTeamResult

CANARY = "CANARY-7f3a"
PROMPTFOO = "promptfoo@0.124.1"


class FakeTarget:
    def __init__(
        self, *, wrap: bool = True, gullible: bool = False, host: str = "127.0.0.1", port: int = 0
    ) -> None:
        raise NotImplementedError


def config(
    target_url: str,
    *,
    purpose: str,
    tests: Iterable[RedTeamCase] = (),
    rubric_per_technique: int = 1,
) -> dict:
    raise NotImplementedError


def eval_config(config: dict) -> dict:
    raise NotImplementedError


def write(config: dict, path: Path) -> None:
    raise NotImplementedError


def cases(corpus: Iterable[Item]) -> list[RedTeamCase]:
    raise NotImplementedError


def ask(target_url: str, prompt: str, *, timeout: float = 10.0) -> dict:
    raise NotImplementedError


def leaked(case: RedTeamCase, reply: dict) -> bool:
    raise NotImplementedError


def run(cases: Iterable[RedTeamCase], target_url: str) -> RedTeamResult:
    raise NotImplementedError
