from pathlib import Path

from pydantic import BaseModel

from evals_lab.types import Agreement, Outcome


class Label(BaseModel):
    outcome: Outcome
    category: str
    note: str = ""


class Labels(BaseModel):
    entries: dict[str, Label]

    @classmethod
    def read(cls, path: Path, known_ids: set[str] | None = None) -> "Labels":
        raise NotImplementedError


def agreement(a: Labels, b: Labels) -> Agreement:
    raise NotImplementedError
