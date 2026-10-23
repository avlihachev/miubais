import json
import os
from pathlib import Path
from typing import Any

ENV = "MIUBAIS_LIVE_REPORT"
_outcomes: dict[str, tuple[str, str]] = {}


def _reason(report: Any) -> str:
    longrepr = report.longrepr
    text = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return text.removeprefix("Skipped: ")


def pytest_runtest_logreport(report: Any) -> None:
    if "live" not in report.keywords:
        return
    if report.skipped and report.when in ("setup", "call"):
        _outcomes[report.nodeid] = ("skipped", _reason(report))
    elif report.when == "call":
        _outcomes[report.nodeid] = (report.outcome, "")
    elif report.failed:
        _outcomes[report.nodeid] = ("failed", "")


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    path = os.environ.get(ENV)
    if not path:
        return
    outcomes = list(_outcomes.values())
    summary = {
        "passed": sum(1 for outcome, _ in outcomes if outcome == "passed"),
        "skipped": [reason for outcome, reason in outcomes if outcome == "skipped"],
    }
    Path(path).write_text(json.dumps(summary))
