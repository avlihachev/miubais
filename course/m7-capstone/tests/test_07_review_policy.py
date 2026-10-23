import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from capstone.types import BLOCKER_KINDS, CATEGORIES
from conftest import FIXTURE, LAB, PR_IDS

DECISIONS = ("merge", "hold", "block")
MIN_AGREEMENT = 10
HEADING = re.compile(r"^#+\s*auto-block categories\s*$", re.IGNORECASE)
TERM = re.compile(r"[a-z][a-z0-9-]*[a-z0-9]")
SUMMARY_LINE = re.compile(r"^(pr-\d\d)\s+(merge|hold|block)\b", re.MULTILINE)


@pytest.fixture(scope="module")
def policy() -> str:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "REVIEW_POLICY.md"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root")
    return path.read_text()


def _cell(value: str) -> str:
    return value.strip().strip("`*").strip()


def parse_rows(text: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.lstrip().startswith("|") or len(cells) != 3:
            continue
        pr, decision, reason = cells
        pr = _cell(pr)
        if pr.lower() == "pr" or set(pr) <= set("-: "):
            continue
        rows.append((pr, _cell(decision).lower(), reason))
    return rows


def auto_block(text: str) -> list[str]:
    found, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            inside = bool(HEADING.match(line.strip()))
            continue
        item = line.strip()
        if inside and item[:1] in ("-", "*"):
            first = TERM.search(item[1:].lower())
            if first:
                found.append(first.group())
    return found


def cited(reason: str) -> set[str]:
    return {t for t in TERM.findall(reason.lower()) if t in CATEGORIES or t in BLOCKER_KINDS}


def evidence(entry: dict) -> set[str]:
    return {f["category"] for f in entry["findings"]} | set(entry["blockers"])


def agreement(rows, decisions: dict[str, str]) -> int:
    return sum(1 for pr, decision, _ in rows if decisions.get(pr) == decision)


def citation_problems(rows, labels) -> dict[str, str]:
    problems = {}
    for pr, decision, reason in rows:
        if decision != "block" or pr not in labels:
            continue
        if not cited(reason) & evidence(labels[pr]):
            problems[pr] = f"cite a blocker kind or category found in {pr}, got {reason!r}"
    return problems


def test_one_row_per_pr(policy):
    prs = [pr for pr, _, _ in parse_rows(policy)]
    assert sorted(prs) == PR_IDS, f"expected one row for each of {PR_IDS}, got {prs}"


def test_decisions_come_from_the_list(policy):
    wrong = {pr: d for pr, d, _ in parse_rows(policy) if d not in DECISIONS}
    assert not wrong, f"use one of {DECISIONS}: {wrong}"


def test_every_row_has_a_reason(policy):
    empty = [pr for pr, _, reason in parse_rows(policy) if not _cell(reason)]
    assert not empty, f"give a reason for {empty}"


def test_decisions_agree_with_the_key(policy, key):
    agreed = agreement(parse_rows(policy), key["decisions"])
    assert agreed >= MIN_AGREEMENT, f"{agreed} of 12 decisions agree, need {MIN_AGREEMENT}"


def test_every_block_cites_its_own_evidence(policy, labels):
    problems = citation_problems(parse_rows(policy), labels)
    assert not problems, problems


def test_auto_block_categories(policy, key):
    listed = auto_block(policy)
    assert listed, "add an '## Auto-block categories' section with one category per bullet"
    unknown = sorted(set(listed) - set(CATEGORIES))
    assert not unknown, f"not categories: {unknown}"
    missing = sorted(set(key["auto_block_required"]) - set(listed))
    assert not missing, f"these categories block without a human: {missing}"
    wrong = sorted(set(key["auto_block_forbidden"]) & set(listed))
    assert not wrong, f"these never block on their own: {wrong}"


def test_the_key_is_the_labels_decisions(key, labels):
    assert key["decisions"] == {pr: entry["decision"] for pr, entry in labels.items()}
    blocking = {
        f["category"] for e in labels.values() for f in e["findings"] if f["severity"] == "blocker"
    }
    assert set(key["auto_block_required"]) <= blocking
    assert not set(key["auto_block_forbidden"]) & blocking


def _table(decisions: dict[str, str], reason: str = "style") -> str:
    rows = [f"| {pr} | {d} | {reason} |" for pr, d in decisions.items()]
    return "| pr | decision | reason |\n| --- | --- | --- |\n" + "\n".join(rows)


def test_a_constant_decision_is_rejected(key):
    for constant in DECISIONS:
        rows = parse_rows(_table(dict.fromkeys(PR_IDS, constant)))
        assert agreement(rows, key["decisions"]) < MIN_AGREEMENT, constant


def test_three_wrong_is_not_enough(key):
    answers = dict(key["decisions"])
    for pr in PR_IDS[:3]:
        answers[pr] = "merge" if answers[pr] != "merge" else "block"
    assert agreement(parse_rows(_table(answers)), key["decisions"]) == 9 < MIN_AGREEMENT


def test_a_block_citing_another_prs_evidence_is_rejected(labels):
    rows = parse_rows(
        "| pr | decision | reason |\n|---|---|---|\n"
        "| pr-08 | block | `secret-in-code` |\n"
        "| pr-01 | block | secret-in-code |\n"
        "| pr-10 | **block** | conflict: the patch does not apply |\n"
        "| pr-02 | block | looks risky |\n"
    )
    assert sorted(citation_problems(rows, labels)) == ["pr-01", "pr-02"]


def test_the_auto_block_section_is_read_by_bullets():
    text = (
        "# Policy\n\n## Auto-block categories\n\n- `secret-in-code`: a leaked token\n"
        "* migration-number-collision\n\nNot style, which a human decides.\n\n"
        "## Other\n\n- style\n"
    )
    assert auto_block(text) == ["secret-in-code", "migration-number-collision"]


@pytest.mark.slow
def test_the_fake_pipeline_prints_a_verdict_per_pr(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "capstone.report",
            "--fake",
            "--repo",
            str(FIXTURE),
            "--out",
            str(tmp_path),
            "--answers",
            str(LAB / "tests" / "FAKEREVIEW.yaml"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr
    verdicts = dict(SUMMARY_LINE.findall(proc.stdout))
    assert sorted(verdicts) == PR_IDS, proc.stdout
    assert (tmp_path / "REPORT.md").is_file()
