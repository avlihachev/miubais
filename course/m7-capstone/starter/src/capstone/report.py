from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from capstone.review import Reviewer
from capstone.types import PR, Blocker, Finding, Label, MetricsReport, Ranked

VERDICTS = ("merge", "hold", "block")


@dataclass
class PRReport:
    pr_id: str
    title: str
    verdict: str
    review: str
    verify: str
    blockers: list[Blocker]
    findings: list[Finding]
    reason: str = ""
    summary: str = ""
    verify_note: str | None = None
    error: str | None = None
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_ms: int = 0


@dataclass
class Report:
    rows: list[PRReport]
    ranked: list[Ranked]
    as_of: date
    duration_ms: int
    metrics: MetricsReport | None = None
    reviewer: str = ""
    model: str | None = None
    max_budget_usd: float | None = None
    max_turns: int | None = None
    agree_with_key: int | None = None
    files: dict[str, Path] = field(default_factory=dict)

    @property
    def total_cost_usd(self) -> float:
        return sum(row.cost_usd for row in self.rows)

    @property
    def by_verdict(self) -> dict[str, int]:
        counts = Counter(row.verdict for row in self.rows)
        return {v: counts.get(v, 0) for v in VERDICTS}


def verdict(findings: list[Finding], found: list[Blocker], reviewed: bool = True) -> str:
    raise NotImplementedError


def run_all(
    repo: Path,
    prs: list[PR],
    reviewer: Reviewer,
    *,
    as_of: date,
    out_dir: Path,
    run_tests: bool = True,
    labels: dict[str, list[Label]] | None = None,
    key: dict[str, str] | None = None,
) -> Report:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
