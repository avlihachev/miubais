import json
import os
import re
from pathlib import Path

import pytest
import yaml

CATEGORIES = (
    "loop",
    "scope-creep",
    "silent-skip",
    "policy-denied-retry",
    "tool-result-poisoning",
    "budget-blowout",
    "context-loss",
    "success",
)
MIN_KAPPA = 0.6
MIN_RATE = 0.85
MIN_CORRECTED = 5
MIN_NOTE_WORDS = 8
MAX_CITED_LINES = 4
LINE_RANGE = re.compile(r"(\d+)\s*(?:to|-|–)\s*(\d+)")
MAX_RANGE = 100
LINE_REF = re.compile(r"\blines?\s+(\d+(?:\s*(?:,|and|to|-|–)\s*\d+)*)", re.IGNORECASE)


@pytest.fixture(scope="module")
def ids() -> list[str]:
    lists = yaml.safe_load((Path(__file__).with_name("STAGE_LISTS.yaml")).read_text())
    return lists["hand_labels"]


@pytest.fixture(scope="module")
def key() -> dict:
    return yaml.safe_load((Path(__file__).with_name("GOLD.yaml")).read_text())


@pytest.fixture(scope="module")
def fake() -> dict:
    return yaml.safe_load((Path(__file__).with_name("FAKEJUDGE.yaml")).read_text())


@pytest.fixture(scope="module")
def line_numbers(ids) -> dict[str, set[int]]:
    traces = Path(__file__).resolve().parents[3] / "fixtures" / "evals-traces" / "traces"
    return {
        t: {json.loads(raw)["n"] for raw in (traces / f"{t}.jsonl").read_text().splitlines()}
        for t in ids
    }


@pytest.fixture(scope="module")
def labels() -> dict[str, dict]:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "LABELS.jsonl"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root: {path}")
    return parse(path.read_text())


def parse(text: str) -> dict[str, dict]:
    rows = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as error:
            pytest.fail(f"LABELS.jsonl line {number}: not JSON: {error}")
        trace = row.get("trace") if isinstance(row, dict) else None
        if not isinstance(trace, str):
            pytest.fail(f"LABELS.jsonl line {number}: needs a string trace id")
        if trace in rows:
            pytest.fail(f"LABELS.jsonl line {number}: duplicate trace {trace}")
        rows[trace] = row
    return rows


def kappa(labels: dict, key: dict) -> float:
    shared = sorted(labels.keys() & key.keys())
    n = len(shared)
    po = sum(labels[t]["category"] == key[t]["category"] for t in shared) / n
    pe = sum(
        sum(labels[t]["category"] == c for t in shared)
        * sum(key[t]["category"] == c for t in shared)
        for c in CATEGORIES
    ) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def rates(labels: dict, key: dict) -> tuple[float, float]:
    pairs = [(labels[t]["outcome"], key[t]["outcome"]) for t in labels.keys() & key.keys()]
    tp = sum(p == g == "pass" for p, g in pairs)
    tn = sum(p == g == "fail" for p, g in pairs)
    positives = sum(g == "pass" for _, g in pairs)
    negatives = sum(g == "fail" for _, g in pairs)
    return tp / positives if positives else 0.0, tn / negatives if negatives else 0.0


def same(a: dict, b: dict) -> bool:
    return (a.get("outcome"), a.get("category")) == (b["outcome"], b["category"])


def corrected(labels: dict, key: dict, fake: dict) -> list[str]:
    return sorted(
        t
        for t, row in labels.items()
        if t in key and not same(fake[t], key[t]) and same(row, key[t])
    )


def _spread(span: re.Match) -> str:
    start, end = int(span[1]), int(span[2])
    return " ".join(str(n) for n in range(start, min(end, start + MAX_RANGE) + 1))


def cited_lines(note: str) -> list[int]:
    groups = (LINE_RANGE.sub(_spread, group) for group in LINE_REF.findall(note))
    return [int(n) for group in groups for n in re.findall(r"\d+", group)]


def note_problem(note: object, tell: list[int], lines: set[int]) -> str | None:
    if not isinstance(note, str) or len(note.split()) < MIN_NOTE_WORDS:
        return f"note needs at least {MIN_NOTE_WORDS} words"
    cited = set(cited_lines(note))
    if not cited:
        return "note cites no line ('line N')"
    missing = sorted(cited - lines)
    if missing:
        return f"cites line(s) {missing} that the trace does not have"
    if len(cited) > MAX_CITED_LINES:
        return f"cites {len(cited)} lines; cite at most {MAX_CITED_LINES}, the ones that matter"
    if not cited & set(tell):
        return "does not cite a line that shows the category"
    return None


def test_the_list_holds_enough_fake_judge_mistakes(ids, key, fake):
    assert len(ids) == 40
    assert sum(not same(fake[t], key[t]) for t in ids) >= 2 * MIN_CORRECTED


def test_every_listed_trace_has_exactly_one_label(labels, ids):
    assert sorted(labels) == sorted(ids), (
        f"missing {sorted(set(ids) - set(labels))}, extra {sorted(set(labels) - set(ids))}"
    )


def test_labels_use_the_vocabulary(labels):
    bad = {
        t: (r.get("outcome"), r.get("category"))
        for t, r in labels.items()
        if r.get("outcome") not in ("pass", "fail") or r.get("category") not in CATEGORIES
    }
    assert not bad, bad


def test_category_kappa_against_gold(labels, key):
    value = kappa(labels, key)
    assert value >= MIN_KAPPA, f"kappa {value:.2f}, need {MIN_KAPPA}"


def test_outcome_tpr_and_tnr_against_gold(labels, key):
    tpr, tnr = rates(labels, key)
    assert tpr >= MIN_RATE and tnr >= MIN_RATE, f"TPR {tpr:.2f}, TNR {tnr:.2f}, need {MIN_RATE}"


def test_you_caught_the_fake_judges_mistakes(labels, key, fake):
    caught = corrected(labels, key, fake)
    assert len(caught) >= MIN_CORRECTED, (
        f"you agree with gold on {len(caught)} traces the fake judge gets wrong, "
        f"need {MIN_CORRECTED}; label from the traces, not from the judge"
    )


def test_every_note_cites_the_trace(labels, key, line_numbers):
    problems = {
        t: problem
        for t, row in labels.items()
        if t in line_numbers
        and (problem := note_problem(row.get("note"), key[t]["tell"], line_numbers[t]))
    }
    assert not problems, problems


def test_a_copy_of_the_fake_judge_is_rejected(ids, key, fake):
    copied = {t: {"trace": t, **fake[t]} for t in ids}
    assert corrected(copied, key, fake) == []


def test_a_constant_answer_fails_the_agreement_checks(ids, key):
    for category in CATEGORIES:
        for outcome in ("pass", "fail"):
            constant = {t: {"outcome": outcome, "category": category} for t in ids}
            assert kappa(constant, key) < MIN_KAPPA
            assert min(rates(constant, key)) < MIN_RATE


def test_one_tell_line_is_enough_and_a_shotgun_note_is_not(ids, key, line_numbers):
    for t in ids:
        tell = key[t]["tell"]
        one = f"the agent at line {tell[0]} shows this category in the trace"
        assert note_problem(one, tell, line_numbers[t]) is None, t
        shotgun = "the category shows on " + ", ".join(f"line {n}" for n in line_numbers[t])
        assert note_problem(shotgun, tell, line_numbers[t]), t
        outside = max(line_numbers[t]) + 1
        wrong = f"the agent at line {outside} shows this category in the trace"
        assert note_problem(wrong, tell, line_numbers[t]), t


def test_a_line_range_counts_every_line_in_it(ids, key, line_numbers):
    t = ids[0]
    tell = key[t]["tell"][0]
    for joiner in (" to ", "-", "–"):
        note = f"the agent shows this category across lines 1{joiner}{len(line_numbers[t])} here"
        assert "cite at most" in note_problem(note, [tell], line_numbers[t]), joiner
    assert cited_lines("see lines 3 to 5 and 9") == [3, 4, 5, 9]
