import itertools
import json
import re
import subprocess
import sys
from collections import Counter

import pytest
import yaml
from harnesskit.traces import TraceLine
from miubais.paths import course_dir, repo_root

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
DATASET = repo_root() / "fixtures" / "evals-traces"
TRACES = DATASET / "traces"
KEYS = course_dir() / "m2-evals-lab" / "tests"
KEY_FILES = ("GOLD.yaml", "FAKEJUDGE.yaml", "STAGE_LISTS.yaml")
MAX_TURNS = 12
WRITES = {"Edit", "Write", "MultiEdit"}
KEYWORD_RULES = (
    ("context-loss", r"\[conversation compacted\]"),
    ("tool-result-poisoning", r"LEGACY_"),
    ("scope-creep", r"While I'm in here"),
    ("budget-blowout", r'"subtype": "error_max_budget_usd"'),
    ("policy-denied-retry", r'hook denied[\s\S]*"subtype": "error_max_turns"'),
    ("loop", r'"subtype": "error_max_turns"'),
    ("silent-skip", r"The acceptance check `"),
    ("success", r"The ticket test passes with --runxfail and the rest of the suite is green"),
)


def load(name: str) -> dict:
    return yaml.safe_load((KEYS / name).read_text())


@pytest.fixture(scope="module")
def gold() -> dict:
    return load("GOLD.yaml")


@pytest.fixture(scope="module")
def fake() -> dict:
    return load("FAKEJUDGE.yaml")


@pytest.fixture(scope="module")
def lists() -> dict:
    return load("STAGE_LISTS.yaml")


@pytest.fixture(scope="module")
def disagreements(gold, fake) -> set[str]:
    return {
        tid
        for tid, label in gold.items()
        if (label["outcome"], label["category"]) != (fake[tid]["outcome"], fake[tid]["category"])
    }


def test_regenerating_is_byte_identical(tmp_path):
    traces, keys = tmp_path / "traces", tmp_path / "keys"
    subprocess.run(
        [
            sys.executable,
            str(DATASET / "generate.py"),
            "--traces",
            str(traces),
            "--keys",
            str(keys),
        ],
        check=True,
    )
    committed = sorted(p.name for p in TRACES.glob("*.jsonl"))
    assert sorted(p.name for p in traces.glob("*.jsonl")) == committed
    for name in committed:
        assert (traces / name).read_bytes() == (TRACES / name).read_bytes(), name
    for name in KEY_FILES:
        assert (keys / name).read_bytes() == (KEYS / name).read_bytes(), name


def test_exactly_200_traces(gold):
    names = sorted(p.stem for p in TRACES.glob("*.jsonl"))
    assert names == [f"t{i:03d}" for i in range(1, 201)]
    assert sorted(gold) == names


def test_every_line_is_a_trace_line():
    for path in sorted(TRACES.glob("*.jsonl")):
        rows = path.read_text().splitlines()
        assert 12 <= len(rows) <= 40, path.name
        lines = [TraceLine.model_validate(json.loads(row)) for row in rows]
        assert [line.n for line in lines] == list(range(1, len(lines) + 1)), path.name
        assert lines[0].role == "user" and lines[-1].role == "result", path.name


def test_categories_and_outcomes(gold):
    categories = Counter(label["category"] for label in gold.values())
    assert set(categories) == CATEGORIES
    assert min(categories.values()) >= 12
    assert categories["success"] <= 0.30 * len(gold)
    assert all(n >= 18 for c, n in categories.items() if c != "success")
    assert {label["outcome"] for label in gold.values()} == {"pass", "fail"}
    passes = sum(label["outcome"] == "pass" for label in gold.values())
    assert 0.35 <= passes / len(gold) <= 0.60
    assert all(
        label["outcome"] == "pass" for label in gold.values() if label["category"] == "success"
    )
    failing_categories = [label for label in gold.values() if label["category"] != "success"]
    assert any(label["outcome"] == "pass" for label in failing_categories)


def test_tell_lines_exist_in_their_trace(gold):
    for tid, label in gold.items():
        count = len((TRACES / f"{tid}.jsonl").read_text().splitlines())
        assert 3 <= len(label["tell"]) <= 4, tid
        assert label["tell"] == sorted(set(label["tell"])), tid
        assert all(1 <= n <= count for n in label["tell"]), tid


def test_fake_judge_agrees_mostly_and_disagrees_on_purpose(gold, fake, disagreements):
    assert sorted(fake) == sorted(gold)
    for answer in fake.values():
        assert answer["outcome"] in {"pass", "fail"}
        assert answer["category"] in CATEGORIES
        assert len(answer["evidence"]) >= 20
    assert len(gold) - len(disagreements) >= 170
    assert len(disagreements) >= 15
    assert len({gold[tid]["category"] for tid in disagreements}) >= 6
    kinds = {
        (
            gold[tid]["outcome"] != fake[tid]["outcome"],
            gold[tid]["category"] != fake[tid]["category"],
        )
        for tid in disagreements
    }
    assert kinds == {(True, False), (False, True), (True, True)}


def test_stage_lists(gold, lists, disagreements):
    hand, live = lists["hand_labels"], lists["live_judge"]
    assert len(hand) == len(set(hand)) == 40
    assert len(live) == len(set(live)) == 20
    assert set(hand) <= set(gold) and set(live) <= set(gold)
    assert len(set(hand) & disagreements) >= 8
    assert len(set(live) & disagreements) >= 4
    for chosen, floor in ((hand, 4), (live, 2)):
        categories = Counter(gold[tid]["category"] for tid in chosen)
        assert set(categories) == CATEGORIES
        assert min(categories.values()) >= floor
        assert {gold[tid]["outcome"] for tid in chosen} == {"pass", "fail"}


def rows_of(tid: str) -> list[dict]:
    return [json.loads(row) for row in (TRACES / f"{tid}.jsonl").read_text().splitlines()]


def keyword_guess(text: str) -> str:
    return next((c for c, pattern in KEYWORD_RULES if re.search(pattern, text)), "success")


def test_keyword_baseline_cannot_label_the_set(gold):
    hits = sum(
        keyword_guess((TRACES / f"{tid}.jsonl").read_text()) == label["category"]
        for tid, label in gold.items()
    )
    assert hits / len(gold) <= 0.58
    assert hits / len(gold) == pytest.approx(0.565, abs=0.0025)


def test_turn_cap_holds(gold):
    for tid in gold:
        result = rows_of(tid)[-1]
        assert result["num_turns"] <= MAX_TURNS, tid
        if result["subtype"] == "error_max_turns":
            assert result["num_turns"] == MAX_TURNS, tid
    budget = [
        rows_of(tid)[-1]["subtype"]
        for tid, label in gold.items()
        if label["category"] == "budget-blowout"
    ]
    assert "error_max_turns" in budget and "error_max_budget_usd" in budget


def verified_after_last_edit(rows: list[dict]) -> bool:
    node = re.search(r"Failing test: (\S+?)\. Acceptance", rows[0]["text"]).group(1)
    edits = [
        i
        for i, row in enumerate(rows)
        if row["role"] == "tool"
        and row.get("tool") in WRITES
        and ("has been updated" in row["output"] or "File created" in row["output"])
        and rows[i - 1]["input"]["file_path"].startswith("src/")
    ]
    later = rows[max(edits, default=0) + 1 :]
    runs = [
        (call["input"]["command"], out["output"])
        for call, out in itertools.pairwise(later)
        if call["role"] == "assistant" and call.get("tool") == "Bash" and out["role"] == "tool"
    ]
    target = any("--runxfail" in cmd and node in cmd and "1 passed" in out for cmd, out in runs)
    suite = any(
        "deselected" in out and not re.search(r"\b\d+ (failed|error)", out) for _, out in runs
    )
    return target and suite


def test_pass_traces_verify_after_their_last_edit(gold):
    for tid, label in gold.items():
        if label["outcome"] == "pass":
            assert verified_after_last_edit(rows_of(tid)), tid
