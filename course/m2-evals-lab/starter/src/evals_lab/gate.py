import sys

from evals_lab.types import GateResult, Run, RunSummary


def summarise(run: Run) -> RunSummary:
    raise NotImplementedError


def compare(run: RunSummary, baseline: RunSummary) -> GateResult:
    raise NotImplementedError


def main(argv: list[str]) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
