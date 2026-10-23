import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from miubais.cli import app
from miubais.exercises import load_exercise
from miubais.model import FakeModelClient, ModelError, ModelRequest, ModelResult
from miubais.tutor import evals
from miubais.tutor.evals import (
    RUNS_DIR,
    EvalCase,
    EvalError,
    case_hash,
    run_cases,
)
from miubais.tutor.hint import Hint
from typer.testing import CliRunner


def reply(text):
    return ModelResult(text=text, structured=None, cost_usd=0.01, session_id="sid", model="m")


@pytest.fixture
def sample_case():
    return EvalCase(
        exercise="x-sample",
        stage="01-add",
        learner_src={"src/sample_lab/__init__.py": "def add(a, b):\n    return a - b\n"},
        failing_output="assert add(1, 2) == 3",
        must_mention_all=[["sum", "add"]],
        must_not_contain=["a + b"],
        file="x-sample-01.yaml",
    )


def test_eval_report_thresholds(sample_case, fixture_course, monkeypatch):
    good = reply("the test expects the sum of two ints")
    report = asyncio.run(run_cases([sample_case], FakeModelClient([good]), fixture_course))
    assert report.leaks == 0 and report.concept_hits == 1 and report.passed
    monkeypatch.setattr("miubais.tutor.hint.leak_terms_for", lambda ex: {"compute_total_secret"})
    bad = reply("use compute_total_secret")
    report = asyncio.run(run_cases([sample_case], FakeModelClient([bad, bad]), fixture_course))
    assert report.leaks == 1 and not report.passed


def test_banned_substring_counts_as_leak(sample_case, fixture_course):
    leaky = reply("the sum is a + b")
    report = asyncio.run(run_cases([sample_case], FakeModelClient([leaky]), fixture_course))
    assert report.leaks == 1 and not report.passed
    assert report.failures == ["x-sample-01.yaml: leak"]


def test_identifiers_in_the_learner_diff_are_not_leaks(sample_case, fixture_course, monkeypatch):
    monkeypatch.setattr("miubais.tutor.hint.leak_terms_for", lambda ex: {"helper_name"})
    case = sample_case.model_copy(
        update={"learner_src": {"src/sample_lab/__init__.py": "def helper_name(a, b):\n"}}
    )
    hint = Hint("the sum: check helper_name", "model", 0, model="m", session_id="sid")
    assert evals.score_hints([case], [hint], fixture_course).leaks == 0
    assert evals.score_hints([sample_case], [hint], fixture_course).leaks == 1


def test_rejected_leak_attempts_are_reported(sample_case, fixture_course, monkeypatch):
    monkeypatch.setattr("miubais.tutor.hint.leak_terms_for", lambda ex: {"secretword"})
    replies = [reply("try secretword"), reply("the sum of the two ints")]
    report = asyncio.run(run_cases([sample_case], FakeModelClient(replies), fixture_course))
    assert report.leaks == 1


def test_record_and_replay(sample_case, fixture_course, tmp_path):
    hints = asyncio.run(
        evals.collect_hints(
            [sample_case], FakeModelClient([reply("adds the sum of the ints")]), fixture_course
        )
    )
    path = evals.record_run([sample_case], hints, tmp_path)
    assert (tmp_path / "latest.jsonl").read_text() == path.read_text()
    assert json.loads(path.read_text())["case"] == "x-sample-01.yaml"
    replayed = evals.load_run(tmp_path / "latest.jsonl", [sample_case])
    assert evals.score_hints([sample_case], replayed, fixture_course).passed


def test_overlong_hint_fails_without_counting_as_leak(sample_case, fixture_course):
    long_hint = Hint("the sum " + "word " * 89, "model", 0, model="m", session_id="sid")
    report = evals.score_hints([sample_case], [long_hint], fixture_course)
    assert report.leaks == 0 and report.concept_hits == 1 and not report.passed
    assert report.failures == ["x-sample-01.yaml: hint is 91 words, limit 90"]


def test_unknown_exercise_and_stage_raise_eval_error(sample_case, fixture_course):
    client = FakeModelClient([reply("the sum")])
    missing = sample_case.model_copy(update={"exercise": "nope"})
    with pytest.raises(EvalError, match="unknown exercise"):
        asyncio.run(run_cases([missing], client, fixture_course))
    bad_stage = sample_case.model_copy(update={"stage": "99-x"})
    with pytest.raises(EvalError, match="unknown stage"):
        asyncio.run(run_cases([bad_stage], client, fixture_course))


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("miubais.cli.RUNS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def cases_dir(tmp_path_factory, monkeypatch, sample_case):
    directory = tmp_path_factory.mktemp("cases")
    body = sample_case.model_dump(exclude={"file"})
    (directory / sample_case.file).write_text(yaml.safe_dump(body))
    monkeypatch.setattr("miubais.cli.CASES_DIR", directory)
    return directory


def invoke(fixture_course, *args):
    return CliRunner().invoke(app, ["tutor-eval", "--course", str(fixture_course), *args])


def test_cli_offline_requires_recorded_run(runs_dir, fixture_course, cases_dir):
    result = invoke(fixture_course)
    assert result.exit_code == 1 and "--live" in result.output


def test_cli_without_cases_exits_1_with_one_line(tmp_repo, fixture_course, monkeypatch):
    monkeypatch.chdir(tmp_repo)
    missing = tmp_repo / "tools/miubais/src/miubais/tutor/evals/cases"
    monkeypatch.setattr("miubais.cli.CASES_DIR", missing)
    result = invoke(fixture_course)
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert result.output.strip() == (
        f"no tutor eval cases at {missing}; they stay in the author's private checkout"
    )


def test_cli_offline_replays_recorded_run(runs_dir, fixture_course, cases_dir, sample_case):
    entry = live_entry(sample_case, hint="the sum of two ints")
    (runs_dir / "latest.jsonl").write_text(json.dumps(entry) + "\n")
    result = invoke(fixture_course)
    assert result.exit_code == 0
    assert "cases=1 leaks=0 concept_hits=1 passed=True" in result.output


def live_entry(case, **overrides):
    entry = {
        "case": case.file,
        "case_hash": case_hash(case),
        "hint": "no idea",
        "source": "model",
        "leaks_rejected": 0,
        "model": "m",
        "at": "2026-10-17T00:00:00+00:00",
        "cost_usd": 0.01,
        "session_id": "sid",
    }
    return {**entry, **overrides}


def test_cli_offline_exits_1_when_thresholds_fail(runs_dir, fixture_course, cases_dir, sample_case):
    entry = live_entry(sample_case)
    (runs_dir / "latest.jsonl").write_text(json.dumps(entry) + "\n")
    result = invoke(fixture_course)
    assert result.exit_code == 1
    assert "passed=False" in result.output and "x-sample-01.yaml: no concept hit" in result.output


def snapshot(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob("*.jsonl")}


def test_cli_live_records_run_files(runs_dir, fixture_course, cases_dir, monkeypatch):
    before = snapshot(RUNS_DIR)
    client = FakeModelClient([reply("the sum of two ints")])
    monkeypatch.setattr("miubais.cli.default_client", lambda: client)
    result = invoke(fixture_course, "--live")
    assert result.exit_code == 0 and "passed=True" in result.output
    latest = runs_dir / "latest.jsonl"
    assert json.loads(latest.read_text())["hint"] == "the sum of two ints"
    assert len(list(runs_dir.glob("2*.jsonl"))) == 1
    assert snapshot(RUNS_DIR) == before


def test_cli_unknown_exercise_exits_1_with_message(runs_dir, tmp_path, cases_dir, sample_case):
    (runs_dir / "latest.jsonl").write_text(json.dumps(live_entry(sample_case)) + "\n")
    result = invoke(tmp_path)
    assert result.exit_code == 1 and "unknown exercise" in result.output


def test_fallback_hint_never_counts_as_concept_hit(sample_case, fixture_course):
    fallback = Hint("stage 'add returns the sum' fails; read the test", "fallback", 0)
    report = evals.score_hints([sample_case], [fallback], fixture_course)
    assert report.concept_hits == 0 and not report.passed
    assert "x-sample-01.yaml: fallback hint" in report.failures


def test_record_run_refuses_fallback(sample_case, tmp_path):
    with pytest.raises(EvalError, match="fallback"):
        evals.record_run([sample_case], [Hint("x", "fallback", 0)], tmp_path)
    assert not list(tmp_path.iterdir())


def test_record_run_stores_live_provenance(sample_case, tmp_path):
    hint = Hint("the sum", "model", 0, (), "claude-x", 0.02, "sid-9")
    path = evals.record_run([sample_case], [hint], tmp_path)
    entry = json.loads(path.read_text())
    assert entry["model"] == "claude-x" and entry["session_id"] == "sid-9"
    assert (
        entry["cost_usd"] == 0.02 and entry["at"] and entry["case_hash"] == case_hash(sample_case)
    )


def test_replay_fails_when_case_changed(sample_case, tmp_path):
    path = tmp_path / "latest.jsonl"
    path.write_text(json.dumps(live_entry(sample_case, case_hash="stale")) + "\n")
    with pytest.raises(EvalError, match="x-sample-01.yaml.*changed"):
        evals.load_run(path, [sample_case])


def test_replay_fails_on_entry_without_session(sample_case, tmp_path):
    path = tmp_path / "latest.jsonl"
    path.write_text(json.dumps(live_entry(sample_case, session_id=None)) + "\n")
    with pytest.raises(EvalError, match="not a live recording"):
        evals.load_run(path, [sample_case])


def test_case_hash_ignores_file_name(sample_case):
    assert case_hash(sample_case) == case_hash(sample_case.model_copy(update={"file": "y.yaml"}))
    changed = sample_case.model_copy(update={"must_mention_all": [["other"]]})
    assert case_hash(changed) != case_hash(sample_case)


def test_every_mention_group_must_hit(sample_case, fixture_course):
    case = sample_case.model_copy(update={"must_mention_all": [["sum"], ["integer", "int"]]})
    one = Hint("the sum is wrong", "model", 0, model="m", session_id="sid")
    both = Hint("the sum of two ints", "model", 0, model="m", session_id="sid")
    assert evals.score_hints([case], [one], fixture_course).concept_hits == 0
    assert evals.score_hints([case], [both], fixture_course).concept_hits == 1


def test_hint_at_the_limit_passes(sample_case, fixture_course):
    hint = Hint("the sum " + "word " * 88, "model", 0, model="m", session_id="sid")
    assert evals.score_hints([sample_case], [hint], fixture_course).too_long == 0


def test_record_run_never_overwrites_a_same_day_file(sample_case, tmp_path):
    hint = Hint("the sum", "model", 0, (), "m", 0.0, "sid")
    first = evals.record_run([sample_case], [hint], tmp_path)
    second = evals.record_run([sample_case], [hint], tmp_path)
    third = evals.record_run([sample_case], [hint], tmp_path)
    assert first.name.endswith(".jsonl") and second.stem == f"{first.stem}-2"
    assert third.stem == f"{first.stem}-3" and first.read_text() == second.read_text()


@pytest.fixture
def two_cases_dir(tmp_path_factory, monkeypatch, sample_case):
    directory = tmp_path_factory.mktemp("two-cases")
    body = sample_case.model_dump(exclude={"file"})
    (directory / "x-sample-01.yaml").write_text(yaml.safe_dump(body))
    (directory / "x-sample-02.yaml").write_text(yaml.safe_dump({**body, "stage": "01-add"}))
    monkeypatch.setattr("miubais.cli.CASES_DIR", directory)
    return directory


def test_cli_only_generates_named_cases_and_replays_the_rest(
    runs_dir, fixture_course, two_cases_dir, sample_case, monkeypatch
):
    old = sample_case.model_copy(update={"file": "x-sample-01.yaml"})
    (runs_dir / "2026-10-01.jsonl").write_text(json.dumps(live_entry(old, hint="the sum")) + "\n")
    shutil.copy(runs_dir / "2026-10-01.jsonl", runs_dir / "latest.jsonl")
    client = FakeModelClient([reply("the sum of two ints, live")])
    monkeypatch.setattr("miubais.cli.default_client", lambda: client)
    result = invoke(fixture_course, "--live", "--only", "x-sample-02")
    assert result.exit_code == 0, result.output
    assert len(client.requests) == 1
    entries = [json.loads(line) for line in (runs_dir / "latest.jsonl").read_text().splitlines()]
    assert [(e["case"], e["source"]) for e in entries] == [
        ("x-sample-01.yaml", "replay:2026-10-01.jsonl"),
        ("x-sample-02.yaml", "live"),
    ]
    assert entries[0]["hint"] == "the sum"
    assert entries[1]["hint"] == "the sum of two ints, live"
    assert (runs_dir / "2026-10-01.jsonl").read_text().count("\n") == 1
    replayed = invoke(fixture_course)
    assert replayed.exit_code == 0 and "passed=True" in replayed.output


def test_cli_only_fails_on_a_stale_replayed_case(
    runs_dir, fixture_course, two_cases_dir, sample_case, monkeypatch
):
    stale = live_entry(sample_case, case_hash="stale")
    (runs_dir / "latest.jsonl").write_text(json.dumps(stale) + "\n")
    before = snapshot(runs_dir)
    monkeypatch.setattr("miubais.cli.default_client", lambda: FakeModelClient([]))
    result = invoke(fixture_course, "--live", "--only", "x-sample-02")
    assert result.exit_code == 1
    assert "x-sample-01.yaml" in result.output and "changed" in result.output
    assert snapshot(runs_dir) == before


def test_cli_only_rejects_unknown_case_and_needs_live(runs_dir, fixture_course, two_cases_dir):
    assert invoke(fixture_course, "--only", "x-sample-02").exit_code == 1
    result = invoke(fixture_course, "--live", "--only", "nope")
    assert result.exit_code == 1 and "nope" in result.output


def test_generation_retries_once_after_a_client_error(sample_case, fixture_course):
    client = FakeModelClient(
        [ModelError("message reader crashed", cost_usd=0.01), reply("the sum of two ints")]
    )
    [hint] = asyncio.run(evals.collect_hints([sample_case], client, fixture_course))
    assert hint.source == "model" and hint.text == "the sum of two ints"
    assert hint.cost_usd == pytest.approx(0.02)
    assert len(client.requests) == 2


def test_retry_once_sums_the_cost_of_two_failures():
    client = FakeModelClient(
        [ModelError("down", cost_usd=0.01), ModelError("still down", cost_usd=0.02)]
    )
    request = ModelRequest(system="s", prompt="p", cwd=Path("."), allowed_tools=[])
    with pytest.raises(ModelError) as raised:
        asyncio.run(evals.RetryOnce(client).complete(request))
    assert raised.value.cost_usd == pytest.approx(0.03)


def test_two_client_errors_still_fall_back(sample_case, fixture_course):
    client = FakeModelClient([ModelError("down"), ModelError("down")])
    [hint] = asyncio.run(evals.collect_hints([sample_case], client, fixture_course))
    assert hint.source == "fallback"
    assert evals.score_hints([sample_case], [hint], fixture_course).concept_hits == 0


def test_eval_workspace_is_the_starter_with_the_learner_files(sample_case, fixture_course):
    case = sample_case.model_copy(update={"learner_src": {"src/sample_lab/extra.py": "X = 1\n"}})
    client = FakeModelClient([reply("the sum of two ints")])
    asyncio.run(evals.collect_hints([case], client, fixture_course))
    prompt = client.requests[0].prompt
    assert "+X = 1" in prompt
    assert "starter/sample_lab/__init__.py" not in prompt
    assert "starter/sample_lab/__init__.py" not in evals.case_diff(
        case, load_exercise(fixture_course / "x-sample")
    )
