import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, get_args

from harnesskit.testing import Timed
from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["blocker", "major", "minor"]
Category = Literal[
    "proto-field-reuse",
    "proto-missing-reserved",
    "migration-number-collision",
    "migration-edited-applied",
    "changelog-missing",
    "input-unvalidated",
    "ts-any",
    "test-removed",
    "secret-in-code",
    "error-swallowed",
    "api-breaking",
    "style",
]
BlockerKind = Literal[
    "stale-migration",
    "missing-second-approval",
    "conflict",
    "unreviewed-age",
    "verify-failed",
]
SEVERITIES: tuple[str, ...] = get_args(Severity)
CATEGORIES: tuple[str, ...] = get_args(Category)
BLOCKER_KINDS: tuple[str, ...] = get_args(BlockerKind)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str
    line: int = Field(ge=1)
    severity: Severity
    category: Category
    message: str = Field(min_length=10)
    confidence: float = Field(ge=0, le=1)
    rule: str | None = None


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str
    start: int = Field(ge=1)
    end: int = Field(ge=1)
    category: Category
    severity: Severity


@dataclass(frozen=True)
class Rule:
    name: str
    paths: list[str]
    body: str


@dataclass(frozen=True)
class PR:
    id: str
    dir: Path
    title: str
    author: str
    created_at: date
    approvals: list[str]
    description: str

    @property
    def patch(self) -> Path:
        return self.dir / "patch.diff"

    @classmethod
    def load(cls, dir: Path) -> "PR":
        meta = json.loads((Path(dir) / "meta.json").read_text())
        return cls(
            id=Path(dir).name,
            dir=Path(dir),
            title=meta["title"],
            author=meta["author"],
            created_at=date.fromisoformat(meta["created_at"]),
            approvals=list(meta["approvals"]),
            description=meta["description"],
        )


@dataclass
class ReviewResult:
    findings: list[Finding]
    summary: str
    cost_usd: float = 0.0
    num_turns: int = 0
    session_id: str | None = None
    run: list[Timed] = field(default_factory=list)


@dataclass(frozen=True)
class Applied:
    ok: bool
    conflicts: list[str]
    tree: Path


@dataclass(frozen=True)
class VerifyResult:
    go_ok: bool | None
    ts_ok: bool | None
    output: str
    duration_ms: int

    @property
    def failed(self) -> bool:
        return self.go_ok is False or self.ts_ok is False


@dataclass(frozen=True)
class Reconciled:
    findings: list[Finding]
    summary: str
    verify_note: str | None


@dataclass(frozen=True)
class Blocker:
    kind: BlockerKind
    detail: str
    weight: int


@dataclass(frozen=True)
class Ranked:
    pr_id: str
    score: int
    kinds: list[str]


@dataclass(frozen=True)
class Matches:
    pairs: list[tuple[Finding, Label]]
    unmatched_findings: list[Finding]
    unmatched_labels: list[Label]


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float
    n_findings: int
    n_labels: int


@dataclass(frozen=True)
class MetricsReport:
    overall: Score
    by_severity: dict[str, Score]
    blocker_recall: float
