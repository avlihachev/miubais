from dataclasses import dataclass, field
from typing import Literal

from harnesskit.traces import TraceLine

Outcome = Literal["pass", "fail"]

CATEGORIES = (
    "loop",
    "scope-creep",
    "silent-skip",
    "policy-denied-retry",
    "tool-result-poisoning",
    "budget-blowout",
    "context-loss",
    "success",
)


@dataclass(frozen=True)
class Trace:
    id: str
    lines: list[TraceLine]


@dataclass(frozen=True)
class Agreement:
    kappa: float
    po: float
    pe: float
    n: int


@dataclass(frozen=True)
class Judgement:
    outcome: Outcome
    category: str
    evidence: str


@dataclass(frozen=True)
class Run:
    run_id: str
    at: str
    judgements: dict[str, Judgement] = field(default_factory=dict)
    cost_usd: float = 0.0
    failures: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    tn: int
    fn: int


@dataclass(frozen=True)
class MetricsReport:
    n: int
    tpr: float
    tnr: float
    kappa: float


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    at: str
    pass_rate: float
    counts: dict[str, int]
    n: int


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
