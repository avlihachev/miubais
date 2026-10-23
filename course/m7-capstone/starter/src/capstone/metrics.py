from capstone.types import Finding, Label, Matches, MetricsReport, Score

__all__ = ["Label", "blocker_recall", "match", "precision_recall", "summarise", "trusted"]


def match(findings: list[Finding], labels: list[Label]) -> Matches:
    raise NotImplementedError


def precision_recall(matches: Matches, severity: str | None = None) -> Score:
    raise NotImplementedError


def blocker_recall(matches: Matches) -> float:
    raise NotImplementedError


def summarise(per_pr: dict[str, Matches]) -> MetricsReport:
    raise NotImplementedError


def trusted(report: MetricsReport) -> bool:
    raise NotImplementedError
