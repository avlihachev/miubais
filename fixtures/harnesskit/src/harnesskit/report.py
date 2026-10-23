import json
from typing import Any, Literal

from claude_agent_sdk import ResultMessage
from pydantic import BaseModel, Field

StoppedBy = Literal["success", "max_turns", "budget", "error", "policy"]


class RunReport(BaseModel):
    ticket_id: str
    session_id: str | None
    turns: int
    cost_usd: float
    stopped_by: StoppedBy
    files_changed: list[str]
    tests_passed: bool | None
    verdict: dict | None
    resumed: bool = False
    notes: list[str] = []
    messages: list[Any] = Field(default_factory=list, exclude=True, repr=False)


def stopped_by_from(result: ResultMessage, budget_hit: bool) -> str:
    if budget_hit or result.subtype == "error_max_budget_usd":
        return "budget"
    if result.subtype == "success":
        # the sdk reports a failed final request as subtype success with is_error set
        return "error" if result.is_error else "success"
    if result.subtype == "error_max_turns":
        return "max_turns"
    return "error"


def to_markdown(r: RunReport) -> str:
    tests = "not run" if r.tests_passed is None else ("pass" if r.tests_passed else "fail")
    lines = [
        f"# Run report: {r.ticket_id}",
        "",
        f"- stopped_by: {r.stopped_by}",
        f"- session_id: {r.session_id or 'none'}",
        f"- resumed: {'yes' if r.resumed else 'no'}",
        f"- turns: {r.turns}",
        f"- cost_usd: ${r.cost_usd:.4f}",
        f"- tests_passed: {tests}",
        f"- files_changed: {', '.join(r.files_changed) if r.files_changed else 'none'}",
    ]
    if r.verdict is not None:
        lines += ["", "## Verdict", "", "```json", json.dumps(r.verdict, indent=2), "```"]
    if r.notes:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in r.notes]
    return "\n".join(lines) + "\n"
