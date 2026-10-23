from pathlib import Path

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

from harness_lab.types import ReviewVerdict


def verdict_schema() -> dict:
    raise NotImplementedError


def parse_verdict(structured: dict) -> ReviewVerdict:
    raise NotImplementedError


def reviewer_agent() -> AgentDefinition:
    raise NotImplementedError


def review_options(repo: Path) -> ClaudeAgentOptions:
    raise NotImplementedError
