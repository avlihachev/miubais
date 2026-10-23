import sys
from pathlib import Path

from serving_lab.types import BenchmarkInput, BenchmarkReport

TEMPLATE = Path(__file__).with_name("BENCHMARK_TEMPLATE.md")


def from_inputs(inp: BenchmarkInput) -> BenchmarkReport:
    raise NotImplementedError


def render(report: BenchmarkReport) -> str:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
