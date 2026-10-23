from collections.abc import Callable
from pathlib import Path


class Once:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def run(self, key: str, fn: Callable[[], str]) -> str:
        raise NotImplementedError
