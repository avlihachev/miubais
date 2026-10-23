from pathlib import Path

from harness_lab.types import Verdict


class Guard:
    def __init__(self, roots: list[Path], blocked: list[str]) -> None:
        raise NotImplementedError

    def check(self, tool: str, args: dict, cwd: Path) -> Verdict:
        raise NotImplementedError
