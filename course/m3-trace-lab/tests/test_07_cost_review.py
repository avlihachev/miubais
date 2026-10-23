import json
import os
import re
from pathlib import Path

import pytest
from conftest import REPO_ROOT

LEVERS = {
    "no-cache": "enable-caching",
    "loop": "cap-turns",
    "big-context": "trim-context",
    "retries": "fix-tool",
    "expensive-model": "downgrade-model",
}
ROWS = 5
MIN_AGREEMENT = 4
CITATION = re.compile(r"\b(r\d{3}):(\d+)\b")


@pytest.fixture(scope="module")
def runs() -> dict[str, tuple[str, int]]:
    found = {}
    for path in sorted((REPO_ROOT / "fixtures" / "harness-runs" / "runs").glob("r*.jsonl")):
        lines = path.read_text().splitlines()
        found[path.stem] = (json.loads(lines[0])["ticket_id"], len(lines))
    return found


@pytest.fixture(scope="module")
def review() -> str:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "COST_REVIEW.md"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root")
    return path.read_text()


def _cell(value: str) -> str:
    return value.strip().strip("`*").strip()


def parse_rows(text: str) -> list[tuple[str, str, str, str]]:
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.lstrip().startswith("|") or len(cells) != 4:
            continue
        ticket, cause, lever, evidence = cells
        ticket = _cell(ticket)
        if ticket.lower() == "ticket" or set(ticket) <= set("-: "):
            continue
        rows.append((ticket, _cell(cause).lower(), _cell(lever).lower(), evidence))
    return rows


def agreement(rows, causes: dict[str, str]) -> int:
    return sum(1 for ticket, cause, _, _ in rows if causes.get(ticket) == cause)


def evidence_problem(ticket: str, evidence: str, runs: dict[str, tuple[str, int]]) -> str | None:
    citations = CITATION.findall(evidence)
    if not citations:
        return "cite a run and a line as rNNN:LL"
    for run_id, line in citations:
        if run_id not in runs:
            return f"{run_id} is not one of the recorded runs"
        owner, length = runs[run_id]
        if owner != ticket:
            return f"{run_id} is a run of {owner}, not of {ticket}"
        if not 2 <= int(line) <= length:
            return f"{run_id}:{line}: cite a line after the meta line, up to {length}"
    return None


def test_one_row_per_top_five_ticket(review, key):
    tickets = [ticket for ticket, _, _, _ in parse_rows(review)]
    assert len(tickets) == ROWS, f"expected {ROWS} rows, got {len(tickets)}: {tickets}"
    assert sorted(tickets) == sorted(key["top_five"]), (
        f"the five costliest tickets are not {sorted(tickets)}; run the stage 06 query"
    )


def test_causes_and_levers_come_from_the_lists(review):
    rows = parse_rows(review)
    causes = {cause for _, cause, _, _ in rows} - LEVERS.keys()
    levers = {lever for _, _, lever, _ in rows} - set(LEVERS.values())
    assert not causes, f"unknown causes {sorted(causes)}; use one of {sorted(LEVERS)}"
    assert not levers, f"unknown levers {sorted(levers)}; use one of {sorted(LEVERS.values())}"


def test_causes_agree_with_the_key(review, key):
    agreed = agreement(parse_rows(review), key["causes"])
    assert agreed >= MIN_AGREEMENT, f"{agreed} of {ROWS} causes agree, need {MIN_AGREEMENT}"


def test_each_lever_answers_its_cause(review):
    wrong = {
        ticket: f"{cause} calls for {LEVERS[cause]}, not {lever}"
        for ticket, cause, lever, _ in parse_rows(review)
        if cause in LEVERS and lever != LEVERS[cause]
    }
    assert not wrong, wrong


def test_evidence_cites_a_run_of_that_ticket(review, runs):
    problems = {
        ticket: problem
        for ticket, _, _, evidence in parse_rows(review)
        if (problem := evidence_problem(ticket, evidence, runs))
    }
    assert not problems, problems


def _table(causes: dict[str, str]) -> str:
    rows = [f"| {t} | {c} | {LEVERS[c]} | r001:2 |" for t, c in causes.items()]
    return "| ticket | cause | lever | evidence |\n| --- | --- | --- | --- |\n" + "\n".join(rows)


def test_a_constant_cause_is_rejected(key):
    for constant in LEVERS:
        rows = parse_rows(_table(dict.fromkeys(key["top_five"], constant)))
        assert agreement(rows, key["causes"]) < MIN_AGREEMENT, constant


def test_three_of_five_is_not_enough(key):
    answers = {t: key["causes"][t] for t in key["top_five"]}
    for ticket in key["top_five"][:2]:
        answers[ticket] = "loop" if answers[ticket] != "loop" else "retries"
    assert agreement(parse_rows(_table(answers)), key["causes"]) == ROWS - 2 < MIN_AGREEMENT


def test_a_run_of_another_ticket_is_rejected(runs):
    owner, _ = runs["r001"]
    assert evidence_problem(owner, "the cache stays cold at r001:2", runs) is None
    assert "not of" in evidence_problem("002-negative-quantity", "see r001:2", runs)
    assert "meta line" in evidence_problem(owner, "see r001:1", runs)
    assert "rNNN:LL" in evidence_problem(owner, "the second turn of r001", runs)
    assert "not one of" in evidence_problem(owner, "see r999:2", runs)
