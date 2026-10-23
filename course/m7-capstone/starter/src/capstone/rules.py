from pathlib import Path

from capstone.types import Rule

__all__ = ["Rule", "for_files", "load", "matches"]


def load(repo: Path) -> list[Rule]:
    raise NotImplementedError


def matches(pattern: str, path: str) -> bool:
    raise NotImplementedError


def for_files(rules: list[Rule], files: list[str]) -> list[Rule]:
    raise NotImplementedError
