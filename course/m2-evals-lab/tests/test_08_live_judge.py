import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage
from evals_lab import judge, traces
from evals_lab.judge import AgentJudge
from evals_lab.types import Run

MIN_EVIDENCE = 20
MIN_OUTCOME_AGREEMENT = 0.7
EVIDENCE = "Line 14 shows the acceptance test passing after the last edit."


def logged_in() -> bool:
    try:
        from miubais.model import claude_available
    except ImportError:
        proc = subprocess.run(
            ["claude", "auth", "status"], check=False, capture_output=True, text=True
        )
        return proc.returncode == 0 and '"loggedIn": true' in proc.stdout
    return claude_available()


def save(run: Run, model: str, workspace: Path) -> Path:
    path = workspace / "runs" / f"live-{datetime.now(UTC).date().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "model": model,
        "cost_usd": run.cost_usd,
        "judgements": {
            trace_id: {"outcome": j.outcome, "category": j.category, "evidence": j.evidence}
            for trace_id, j in run.judgements.items()
        },
        "failures": run.failures,
    }
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def problems(record: dict, ids: list[str], gold: dict) -> list[str]:
    found = []
    if not record.get("model"):
        found.append("no model")
    cost = record.get("cost_usd")
    if isinstance(cost, bool) or not isinstance(cost, int | float) or cost <= 0:
        found.append(f"cost_usd must be a positive number, got {cost!r}")
    judgements = record.get("judgements", {})
    if sorted(judgements) != sorted(ids):
        found.append(f"judged {sorted(judgements)}, expected {sorted(ids)}")
    short = [t for t, j in judgements.items() if len(j.get("evidence", "")) < MIN_EVIDENCE]
    if short:
        found.append(f"evidence under {MIN_EVIDENCE} characters for {short}")
    agreed = sum(j.get("outcome") == gold[t]["outcome"] for t, j in judgements.items())
    if agreed < MIN_OUTCOME_AGREEMENT * len(ids):
        found.append(f"outcome agrees with gold on {agreed} of {len(ids)}")
    return found


@pytest.fixture
def workspace() -> Path:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    return Path(root)


@pytest.fixture
def picked(traces_dir, stage_lists):
    ids = set(stage_lists["live_judge"])
    return [t for t in traces.load(traces_dir) if t.id in ids]


def scripted_run(scripted, picked, gold, evidence=EVIDENCE):
    answers = iter(
        {"outcome": gold[t.id]["outcome"], "category": gold[t.id]["category"], "evidence": e}
        for t, e in zip(picked, [evidence] + [EVIDENCE] * (len(picked) - 1), strict=True)
    )

    def fake_query(prompt=None, options=None, **kwargs):
        message = ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            total_cost_usd=0.01,
            structured_output=next(answers),
        )
        return scripted([message])(prompt=prompt, options=options)

    agent = AgentJudge(query_fn=fake_query)
    return agent, judge.run(agent, picked)


def test_the_stored_record_has_model_cost_and_evidence(
    scripted, picked, gold, stage_lists, tmp_path
):
    agent, run = scripted_run(scripted, picked, gold)
    record = json.loads(save(run, agent.model, tmp_path).read_text())
    assert record["model"] == "claude-opus-5-5"
    assert record["cost_usd"] == pytest.approx(0.2)
    assert record["failures"] == {}
    assert problems(record, stage_lists["live_judge"], gold) == []


def test_a_short_evidence_string_fails_the_run(scripted, picked, gold, stage_lists, tmp_path):
    agent, run = scripted_run(scripted, picked, gold, evidence="line 3")
    record = json.loads(save(run, agent.model, tmp_path).read_text())
    assert any("evidence" in p for p in problems(record, stage_lists["live_judge"], gold))


def test_a_run_without_cost_fails(gold, stage_lists):
    ids = stage_lists["live_judge"]
    judgements = {
        t: {"outcome": gold[t]["outcome"], "category": gold[t]["category"], "evidence": EVIDENCE}
        for t in ids
    }
    for cost in (0.0, None, "0.27", True):
        record = {"model": "m", "cost_usd": cost, "judgements": judgements}
        assert any("cost_usd" in p for p in problems(record, ids, gold)), cost


def test_outcome_agreement_below_seventy_percent_fails(gold, stage_lists):
    ids = stage_lists["live_judge"]
    flipped = {"pass": "fail", "fail": "pass"}
    judgements = {
        t: {
            "outcome": flipped[gold[t]["outcome"]] if k < 7 else gold[t]["outcome"],
            "category": gold[t]["category"],
            "evidence": EVIDENCE,
        }
        for k, t in enumerate(ids)
    }
    record = {"model": "m", "cost_usd": 0.2, "judgements": judgements}
    assert problems(record, ids, gold) == ["outcome agrees with gold on 13 of 20"]
    judgements[ids[0]]["outcome"] = gold[ids[0]]["outcome"]
    assert problems(record, ids, gold) == []


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not logged_in(), reason="needs claude-auth")
def test_live_judge_on_twenty_traces(picked, gold, stage_lists, workspace):
    agent = AgentJudge()
    run = judge.run(agent, picked)
    path = save(run, agent.model, workspace)
    record = json.loads(path.read_text())
    agreed = sum(j["outcome"] == gold[t]["outcome"] for t, j in record["judgements"].items())
    same_category = sum(
        j["category"] == gold[t]["category"] for t, j in record["judgements"].items()
    )
    print(
        f"\nlive judge {record['model']}: outcome {agreed}/{len(picked)}, "
        f"category {same_category}/{len(picked)}, failures {len(run.failures)}, "
        f"cost ${record['cost_usd']:.4f}, saved {path}"
    )
    assert path.is_file()
    assert problems(record, stage_lists["live_judge"], gold) == []
