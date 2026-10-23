import os
import re
from pathlib import Path

import pytest
import yaml

CATEGORIES = {
    "loop",
    "scope-creep",
    "silent-skip",
    "policy-denied-retry",
    "tool-result-poisoning",
    "budget-blowout",
    "context-loss",
    "success",
}
MIN_AGREEMENT = 10
MIN_EVIDENCE_WORDS = 8
MAX_CITED_LINES = 4
MIN_FIX_WORDS = 40
LINE_REF = re.compile(r"\blines?\s+(\d+(?:\s*(?:,|and|to|-|–)\s*\d+)*)", re.IGNORECASE)


@pytest.fixture(scope="module")
def key() -> dict:
    return yaml.safe_load((Path(__file__).with_name("KEY.yaml")).read_text())["traces"]


@pytest.fixture(scope="module")
def trace_lengths(key) -> dict[str, int]:
    traces = Path(__file__).resolve().parent.parent / "fixtures" / "traces"
    return {tid: len((traces / f"{tid}.jsonl").read_text().splitlines()) for tid in key}


@pytest.fixture(scope="module")
def failures_md() -> str:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "FAILURES.md"
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
        trace, category, evidence = cells
        trace = _cell(trace).removesuffix(".jsonl")
        if trace.lower() == "trace" or set(trace) <= set("-: "):
            continue
        rows.append((trace, _cell(category).lower(), evidence))
    return rows


def parse_fixes(text: str) -> dict[str, str]:
    match = re.search(r"^## Fixes\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return {}
    fixes = {}
    for paragraph in re.split(r"\n\s*\n", match.group(1).strip()):
        first = paragraph.split(maxsplit=1)[0] if paragraph.split() else ""
        name = first.strip("*`_:.").lower()
        if name in CATEGORIES:
            fixes[name] = paragraph
    return fixes


def cited_lines(evidence: str) -> list[int]:
    return [int(n) for group in LINE_REF.findall(evidence) for n in re.findall(r"\d+", group)]


def evidence_problem(evidence: str, expected: dict, length: int) -> str | None:
    if len(evidence.split()) < MIN_EVIDENCE_WORDS:
        return f"needs at least {MIN_EVIDENCE_WORDS} words"
    lines = cited_lines(evidence)
    missing = [n for n in lines if not 1 <= n <= length]
    if missing:
        return f"cites line(s) {missing} that the trace does not have ({length} lines)"
    if len(set(lines)) > MAX_CITED_LINES:
        return (
            f"cites {len(set(lines))} lines; cite at most {MAX_CITED_LINES}, the ones that matter"
        )
    if set(lines) & set(expected["tell"]):
        return None
    if any(re.search(rf"\b{re.escape(tool)}\b", evidence) for tool in expected["tools"]):
        return None
    return "does not cite a line or tool call that shows the category"


def agreement(rows: list[tuple[str, str, str]], key: dict) -> int:
    return sum(1 for trace, category, _ in rows if key.get(trace, {}).get("category") == category)


def test_every_trace_has_exactly_one_row(failures_md, key):
    ids = [trace for trace, _, _ in parse_rows(failures_md)]
    assert sorted(ids) == sorted(key), f"expected one row per trace {sorted(key)}, got {ids}"


def test_categories_come_from_the_taxonomy(failures_md):
    unknown = {c for _, c, _ in parse_rows(failures_md)} - CATEGORIES
    assert not unknown, f"unknown categories {sorted(unknown)}; use one of {sorted(CATEGORIES)}"


def test_classification_agrees_with_the_key(failures_md, key):
    agreed = agreement(parse_rows(failures_md), key)
    assert agreed >= MIN_AGREEMENT, f"{agreed} of {len(key)} traces agree, need {MIN_AGREEMENT}"


def test_evidence_cites_the_trace(failures_md, key, trace_lengths):
    problems = {
        trace: problem
        for trace, _, evidence in parse_rows(failures_md)
        if trace in key
        and (problem := evidence_problem(evidence, key[trace], trace_lengths[trace]))
    }
    assert not problems, problems


def test_one_fix_paragraph_per_failure_category(failures_md, key):
    needed = {entry["category"] for entry in key.values()} - {"success"}
    fixes = parse_fixes(failures_md)
    missing = sorted(needed - fixes.keys())
    assert not missing, f"## Fixes has no paragraph starting with {missing}"
    short = {c: len(fixes[c].split()) for c in needed if len(fixes[c].split()) < MIN_FIX_WORDS}
    assert not short, f"fix paragraphs need at least {MIN_FIX_WORDS} words: {short}"


def _table(categories: dict[str, str]) -> str:
    rows = [
        f"| {t} | {c} | line 1 shows this clearly in the recorded trace |"
        for t, c in categories.items()
    ]
    return "| trace | category | evidence |\n| --- | --- | --- |\n" + "\n".join(rows)


def test_a_generic_answer_is_rejected(key):
    for constant in sorted(CATEGORIES):
        rows = parse_rows(_table(dict.fromkeys(key, constant)))
        assert agreement(rows, key) < MIN_AGREEMENT


def test_nine_of_twelve_is_not_enough(key):
    answers = {t: entry["category"] for t, entry in key.items()}
    for trace in list(answers)[:3]:
        answers[trace] = "budget-blowout" if answers[trace] != "budget-blowout" else "loop"
    assert agreement(parse_rows(_table(answers)), key) == len(key) - 3 < MIN_AGREEMENT


def test_key_tells_are_narrow(key, trace_lengths):
    for trace, entry in key.items():
        assert 2 <= len(entry["tell"]) <= 4, trace
        assert all(1 <= n <= trace_lengths[trace] for n in entry["tell"]), trace


def test_citing_every_line_is_rejected(key, trace_lengths):
    for trace, entry in key.items():
        shotgun = "the category shows on " + ", ".join(
            f"line {n}" for n in range(1, trace_lengths[trace] + 1)
        )
        assert evidence_problem(shotgun, entry, trace_lengths[trace]), trace


def test_one_tell_line_is_enough(key, trace_lengths):
    for trace, entry in key.items():
        cited = f"the agent at line {entry['tell'][0]} shows this category in the recorded trace"
        assert evidence_problem(cited, entry, trace_lengths[trace]) is None, trace


def test_a_tool_name_counts_only_where_the_key_lists_tools(key, trace_lengths):
    for trace, entry in key.items():
        named = "the Bash Edit Write Grep Read calls in this trace show the category clearly"
        problem = evidence_problem(named, entry, trace_lengths[trace])
        assert (problem is None) == bool(entry["tools"]), trace
