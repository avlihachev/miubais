import json
from pathlib import Path

import pytest
from evals_lab.labels import Labels, agreement
from evals_lab.types import CATEGORIES

LAB = Path(__file__).resolve().parent.parent
LABELS_B = LAB / "fixtures" / "labels_b.jsonl"


def write(path, rows):
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
    return path


def row(trace, outcome="pass", category="success", **extra):
    return {"trace": trace, "outcome": outcome, "category": category, **extra}


def gold_labels(gold, tmp_path, ids=None):
    rows = [row(i, v["outcome"], v["category"]) for i, v in gold.items() if ids is None or i in ids]
    return Labels.read(write(tmp_path / "gold.jsonl", rows))


def test_reads_valid_rows(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t001", note="ok"), row("t002", "fail", "loop")])
    labels = Labels.read(path, known_ids={"t001", "t002"})
    assert labels.entries["t001"].note == "ok"
    assert labels.entries["t002"].outcome == "fail"
    assert labels.entries["t002"].category == "loop"


def test_rejects_duplicate_trace_with_line(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t001"), row("t002"), row("t001")])
    with pytest.raises(ValueError, match="line 3"):
        Labels.read(path)


def test_rejects_unknown_trace_with_line(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t001"), row("t999")])
    with pytest.raises(ValueError, match="line 2"):
        Labels.read(path, known_ids={"t001", "t002"})


def test_unknown_trace_is_accepted_without_known_ids(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t999")])
    assert "t999" in Labels.read(path).entries


def test_rejects_bad_outcome_with_line(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t001"), row("t002"), row("t003", outcome="maybe")])
    with pytest.raises(ValueError, match="line 3"):
        Labels.read(path)


def test_rejects_category_outside_vocabulary_with_line(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t001", category="flaky")])
    with pytest.raises(ValueError, match="line 1"):
        Labels.read(path)


def test_rejects_malformed_json_with_line(tmp_path):
    path = write(tmp_path / "a.jsonl", [row("t001"), "{broken"])
    with pytest.raises(ValueError, match="line 2"):
        Labels.read(path)


def test_perfect_agreement_is_kappa_one(tmp_path):
    rows = [row(f"t{i:03d}", category=c) for i, c in enumerate(CATEGORIES, 1)]
    a = Labels.read(write(tmp_path / "a.jsonl", rows))
    b = Labels.read(write(tmp_path / "b.jsonl", rows))
    result = agreement(a, b)
    assert result.kappa == pytest.approx(1.0)
    assert result.po == 1.0 and result.n == len(CATEGORIES)


def test_chance_level_agreement_is_kappa_zero(tmp_path):
    cats_a = ["loop", "success", "loop", "success"]
    cats_b = ["loop", "loop", "success", "success"]
    a = Labels.read(
        write(tmp_path / "a.jsonl", [row(f"t{i}", category=c) for i, c in enumerate(cats_a)])
    )
    b = Labels.read(
        write(tmp_path / "b.jsonl", [row(f"t{i}", category=c) for i, c in enumerate(cats_b)])
    )
    result = agreement(a, b)
    assert result.po == 0.5 and result.pe == 0.5
    assert result.kappa == pytest.approx(0.0)


def test_kappa_ignores_outcome(tmp_path):
    cats = ["loop", "success", "loop", "success"]
    a = Labels.read(
        write(tmp_path / "a.jsonl", [row(f"t{i}", "pass", c) for i, c in enumerate(cats)])
    )
    b = Labels.read(
        write(tmp_path / "b.jsonl", [row(f"t{i}", "fail", c) for i, c in enumerate(cats)])
    )
    assert agreement(a, b).kappa == pytest.approx(1.0)


def test_agreement_uses_only_the_shared_traces(tmp_path):
    a = Labels.read(write(tmp_path / "a.jsonl", [row("t1"), row("t2", category="loop"), row("t3")]))
    b = Labels.read(write(tmp_path / "b.jsonl", [row("t2", category="loop"), row("t3"), row("t4")]))
    result = agreement(a, b)
    assert result.n == 2
    assert result.po == 1.0


def test_no_shared_traces_raises(tmp_path):
    a = Labels.read(write(tmp_path / "a.jsonl", [row("t1")]))
    b = Labels.read(write(tmp_path / "b.jsonl", [row("t2")]))
    with pytest.raises(ValueError):
        agreement(a, b)


def test_second_annotator_kappa_against_gold(gold, tmp_path):
    ids = {f"t{i:03d}" for i in range(1, 61)}
    b = Labels.read(LABELS_B, known_ids=set(gold))
    assert set(b.entries) == ids
    result = agreement(gold_labels(gold, tmp_path, ids), b)
    po = 47 / 60
    pe = (23 * 23 + 7 * 10 + 4 * 7 + 5 * 5 + 6 * 5 + 8 * 5 + 3 * 3 + 4 * 2) / 60**2
    assert pe == pytest.approx(739 / 3600)
    expected = (po - pe) / (1 - pe)
    assert expected == pytest.approx(2081 / 2861)
    assert result.n == 60
    assert result.po == pytest.approx(po, abs=1e-9)
    assert result.pe == pytest.approx(pe, abs=1e-9)
    assert result.kappa == pytest.approx(expected, abs=1e-6)
    assert result.kappa == pytest.approx(0.727368, abs=1e-6)
