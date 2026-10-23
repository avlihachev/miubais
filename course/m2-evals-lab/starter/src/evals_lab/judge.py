from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

from evals_lab.types import CATEGORIES, Judgement, Run, Trace

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome", "category", "evidence"],
    "properties": {
        "outcome": {"enum": ["pass", "fail"]},
        "category": {"enum": list(CATEGORIES)},
        "evidence": {"type": "string", "minLength": 20},
    },
}


class JudgeError(Exception):
    pass


class Judge(Protocol):
    def judge(self, trace: Trace) -> Judgement: ...


class FakeJudge:
    def __init__(self, answers_path: Path) -> None:
        raise NotImplementedError

    def judge(self, trace: Trace) -> Judgement:
        raise NotImplementedError


class AgentJudge:
    def __init__(self, model: str | None = None, query_fn: Callable | None = None) -> None:
        raise NotImplementedError

    def judge(self, trace: Trace) -> Judgement:
        raise NotImplementedError


def run(judge: Judge, traces: Iterable[Trace]) -> Run:
    raise NotImplementedError
