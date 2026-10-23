from datetime import date
from pathlib import Path

from capstone.types import PR, Applied, Blocker, Ranked, VerifyResult

WEIGHTS = {
    "conflict": 100,
    "verify-failed": 90,
    "stale-migration": 80,
    "missing-second-approval": 60,
    "unreviewed-age": 30,
}


def detect(
    pr: PR,
    repo: Path,
    changed: list[str],
    applied: Applied,
    verify: VerifyResult | None,
    *,
    as_of: date,
) -> list[Blocker]:
    raise NotImplementedError


def score(blockers: list[Blocker]) -> int:
    raise NotImplementedError


def rank(items: list[tuple[PR, list[Blocker]]]) -> list[Ranked]:
    raise NotImplementedError


def to_markdown(ranked: list[Ranked]) -> str:
    raise NotImplementedError
