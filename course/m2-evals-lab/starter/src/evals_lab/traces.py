from pathlib import Path

from evals_lab.types import Trace


def load(dir: Path) -> list[Trace]:
    raise NotImplementedError


def view(trace: Trace) -> str:
    raise NotImplementedError
