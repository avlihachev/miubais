from pathlib import Path

from evals_lab.types import RunSummary


class ScoreHistory:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def record(self, summary: RunSummary) -> None:
        raise NotImplementedError

    def trend(self, n: int) -> list[RunSummary]:
        raise NotImplementedError
