from collections.abc import Callable, Iterable
from dataclasses import dataclass

from injection_lab.types import Detection, Item

THRESHOLD = 0.5


@dataclass(frozen=True)
class DetectorReport:
    tpr: float
    fpr: float
    by_technique: dict[str, float]


def score(text: str, *, channel: str = "tool") -> Detection:
    raise NotImplementedError


def evaluate(items: Iterable[Item], detector: Callable[..., Detection] = score) -> DetectorReport:
    raise NotImplementedError
