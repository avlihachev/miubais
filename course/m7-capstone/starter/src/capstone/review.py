from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from claude_agent_sdk import ClaudeAgentOptions

from capstone.types import PR, ReviewResult, Rule

FINDINGS_SCHEMA: dict = {}


class ReviewError(Exception):
    pass


class Reviewer(Protocol):
    def review(self, pr: PR, tree: Path, rules: list[Rule]) -> ReviewResult: ...


def changed_files(patch_text: str) -> list[str]:
    raise NotImplementedError


def prompt(pr: PR, rules: list[Rule], patch_text: str) -> str:
    raise NotImplementedError


def read_guard(tree: Path) -> Callable:
    raise NotImplementedError


class FakeReviewer:
    def __init__(self, answers_path: Path) -> None:
        self.answers_path = answers_path

    def review(self, pr: PR, tree: Path, rules: list[Rule]) -> ReviewResult:
        raise NotImplementedError


class AgentReviewer:
    def __init__(
        self,
        model: str | None = None,
        query_fn: Callable | None = None,
        max_turns: int = 20,
        max_budget_usd: float = 0.40,
    ) -> None:
        self.model = model
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.last_cost_usd = 0.0
        self._query = query_fn

    def options(self, tree: Path) -> ClaudeAgentOptions:
        raise NotImplementedError

    def review(self, pr: PR, tree: Path, rules: list[Rule]) -> ReviewResult:
        raise NotImplementedError
