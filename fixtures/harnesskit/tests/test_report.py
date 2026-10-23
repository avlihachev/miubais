import pytest
from claude_agent_sdk import ResultMessage
from harnesskit.report import RunReport, stopped_by_from, to_markdown
from pydantic import ValidationError


def result(subtype: str, cost: float | None = 0.1, is_error: bool | None = None) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=8,
        is_error=subtype != "success" if is_error is None else is_error,
        num_turns=3,
        session_id="sess-1",
        total_cost_usd=cost,
    )


@pytest.mark.parametrize(
    ("subtype", "budget_hit", "expected"),
    [
        ("success", False, "success"),
        ("error_max_turns", False, "max_turns"),
        ("error_max_budget_usd", False, "budget"),
        ("error_during_execution", False, "error"),
        ("success", True, "budget"),
        ("error_max_turns", True, "budget"),
    ],
)
def test_stopped_by_from(subtype, budget_hit, expected):
    assert stopped_by_from(result(subtype), budget_hit) == expected


def test_failed_final_request_is_error():
    assert stopped_by_from(result("success", is_error=True), False) == "error"


def report(**overrides) -> RunReport:
    fields = {
        "ticket_id": "001-discount-rounding",
        "session_id": "sess-1",
        "turns": 4,
        "cost_usd": 0.1234,
        "stopped_by": "success",
        "files_changed": ["src/tinyshop/pricing.py"],
        "tests_passed": True,
        "verdict": None,
    }
    return RunReport(**(fields | overrides))


def test_report_defaults():
    r = report()
    assert r.resumed is False and r.notes == []


def test_report_rejects_unknown_stop():
    with pytest.raises(ValidationError):
        report(stopped_by="tired")


def test_to_markdown():
    text = to_markdown(report(stopped_by="budget", notes=["resume failed: x; started fresh"]))
    assert text.startswith("# Run report: 001-discount-rounding")
    assert "stopped_by: budget" in text
    assert "$0.1234" in text
    assert "src/tinyshop/pricing.py" in text
    assert "resume failed: x; started fresh" in text


def test_to_markdown_empty_fields():
    text = to_markdown(report(files_changed=[], tests_passed=None, verdict={"approve": True}))
    assert "files_changed: none" in text
    assert "tests_passed: not run" in text
    assert '"approve": true' in text
