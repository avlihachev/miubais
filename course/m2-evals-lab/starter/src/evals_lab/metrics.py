from evals_lab.labels import Labels
from evals_lab.types import Confusion, MetricsReport, Run


def confusion(run: Run, gold: Labels) -> Confusion:
    raise NotImplementedError


def tpr(c: Confusion) -> float:
    raise NotImplementedError


def tnr(c: Confusion) -> float:
    raise NotImplementedError


def kappa(run: Run, gold: Labels) -> float:
    raise NotImplementedError


def report(run: Run, gold: Labels) -> MetricsReport:
    raise NotImplementedError


def trusted(report: MetricsReport) -> bool:
    raise NotImplementedError
