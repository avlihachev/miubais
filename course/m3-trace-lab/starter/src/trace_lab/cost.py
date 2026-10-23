from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan

from trace_lab.types import Reconciliation, RunTrace, TaskCost


@dataclass(frozen=True)
class Prices:
    table: dict

    @classmethod
    def load(cls, path: Path | None = None) -> "Prices":
        raise NotImplementedError


def span_cost(span: ReadableSpan, prices: Prices) -> float:
    raise NotImplementedError


def per_task(traces: Iterable[RunTrace], prices: Prices) -> dict[str, TaskCost]:
    raise NotImplementedError


def reconcile(trace: RunTrace, prices: Prices) -> Reconciliation:
    raise NotImplementedError
