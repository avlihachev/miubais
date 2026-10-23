import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest
from evals_lab import gate, judge, traces
from evals_lab.judge import FakeJudge
from evals_lab.types import CATEGORIES, Judgement, Run, RunSummary

BASELINE = Path(__file__).resolve().parent.parent / "fixtures" / "baseline.json"


def read_summary(path: Path) -> RunSummary:
    return RunSummary(**json.loads(path.read_text()))


def write_summary(path: Path, summary: RunSummary) -> Path:
    path.write_text(json.dumps(dataclasses.asdict(summary)))
    return path


def shifted(summary: RunSummary, pass_rate: float | None = None, **counts: int) -> RunSummary:
    moved = dict(summary.counts)
    for name, delta in counts.items():
        moved[name.replace("_", "-")] += delta
    return dataclasses.replace(
        summary,
        run_id="candidate",
        pass_rate=summary.pass_rate if pass_rate is None else pass_rate,
        counts=moved,
    )


@pytest.fixture
def baseline():
    return read_summary(BASELINE)


@pytest.fixture
def fake_run(traces_dir, fake_answers_path):
    return judge.run(FakeJudge(fake_answers_path), traces.load(traces_dir))


def test_summarise_counts_every_category_and_the_pass_rate():
    run = Run(
        "r1",
        "2026-10-17T09:00:00+00:00",
        {
            "a": Judgement("pass", "success", "x" * 20),
            "b": Judgement("fail", "loop", "x" * 20),
            "c": Judgement("pass", "loop", "x" * 20),
            "d": Judgement("fail", "silent-skip", "x" * 20),
        },
    )
    summary = gate.summarise(run)
    assert (summary.run_id, summary.at, summary.n) == ("r1", "2026-10-17T09:00:00+00:00", 4)
    assert summary.pass_rate == pytest.approx(0.5)
    assert summary.counts == {c: 0 for c in CATEGORIES} | {
        "success": 1,
        "loop": 2,
        "silent-skip": 1,
    }
    assert list(summary.counts) == list(CATEGORIES)


def test_the_baseline_fixture_is_the_fake_judge_over_all_traces(baseline, fake_run):
    summary = gate.summarise(fake_run)
    assert summary.n == baseline.n == 200
    assert summary.pass_rate == pytest.approx(baseline.pass_rate)
    assert summary.counts == baseline.counts


def test_a_run_identical_to_the_baseline_passes(baseline):
    assert gate.compare(dataclasses.replace(baseline, run_id="again"), baseline).ok is True


def test_a_drop_of_two_and_a_half_points_fails_naming_pass_rate(baseline):
    result = gate.compare(shifted(baseline, pass_rate=baseline.pass_rate - 0.025), baseline)
    assert result.ok is False
    assert len(result.reasons) == 1
    assert "pass_rate" in result.reasons[0]


def test_a_drop_of_exactly_two_points_passes(baseline):
    exactly_two = round(baseline.pass_rate - 0.02, 4)
    assert gate.compare(shifted(baseline, pass_rate=exactly_two), baseline).ok


def test_a_drop_of_two_point_zero_one_points_fails(baseline):
    just_over = round(baseline.pass_rate - 0.0201, 4)
    result = gate.compare(shifted(baseline, pass_rate=just_over), baseline)
    assert result.ok is False
    assert "pass_rate" in result.reasons[0]


def test_rates_are_compared_after_rounding_to_four_decimals(baseline):
    noisy = round(baseline.pass_rate - 0.02, 4) - 0.00004
    assert gate.compare(shifted(baseline, pass_rate=noisy), baseline).ok


def test_a_rise_in_pass_rate_passes(baseline):
    assert gate.compare(shifted(baseline, pass_rate=baseline.pass_rate + 0.1), baseline).ok


def test_four_more_loops_fails_naming_loop(baseline):
    result = gate.compare(shifted(baseline, loop=4, success=-4), baseline)
    assert result.ok is False
    assert len(result.reasons) == 1
    assert "loop" in result.reasons[0]


def test_three_more_loops_passes(baseline):
    assert gate.compare(shifted(baseline, loop=3, success=-3), baseline).ok is True


def test_every_failing_check_gives_its_own_reason(baseline):
    worse = shifted(
        baseline, pass_rate=baseline.pass_rate - 0.05, loop=5, context_loss=4, success=-9
    )
    result = gate.compare(worse, baseline)
    assert result.ok is False
    assert len(result.reasons) == 3
    assert any("pass_rate" in r for r in result.reasons)
    assert any("loop" in r for r in result.reasons)
    assert any("context-loss" in r for r in result.reasons)


def test_slow_drift_passes_against_each_previous_run_but_fails_against_the_baseline(baseline):
    previous = baseline
    for step in range(1, 4):
        current = shifted(baseline, pass_rate=baseline.pass_rate - 0.015 * step)
        assert gate.compare(current, previous).ok, step
        previous = current
    result = gate.compare(current, baseline)
    assert result.ok is False
    assert "pass_rate" in result.reasons[0]


def run_cli(*args: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "evals_lab.gate", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_zero_when_the_gate_passes(tmp_path, baseline):
    run = write_summary(tmp_path / "run.json", dataclasses.replace(baseline, run_id="again"))
    proc = run_cli(run, BASELINE)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_exits_one_and_prints_the_reasons_on_a_drop(tmp_path, baseline):
    drop = shifted(baseline, pass_rate=baseline.pass_rate - 0.025, loop=4, success=-4)
    proc = run_cli(write_summary(tmp_path / "run.json", drop), BASELINE)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "pass_rate" in proc.stdout
    assert "loop" in proc.stdout
