from dataclasses import dataclass, field


@dataclass(frozen=True)
class Verdict:
    ok: bool
    why: str


@dataclass(frozen=True)
class Summary:
    turns: int
    cost_usd: float
    stopped_by: str
    final_text: str


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    severity: str
    note: str


@dataclass(frozen=True)
class ReviewVerdict:
    approve: bool
    findings: list[Finding] = field(default_factory=list)
