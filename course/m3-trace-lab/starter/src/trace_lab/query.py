from collections.abc import Iterable

from trace_lab.cost import Prices
from trace_lab.types import RunTrace, TaskCost


def top_costly(traces: Iterable[RunTrace], prices: Prices, n: int = 5) -> list[TaskCost]:
    raise NotImplementedError


def to_markdown(rows: list[TaskCost]) -> str:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
