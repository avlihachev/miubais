import re

import pytest
import yaml
from claude_agent_sdk import CLIConnectionError, ProcessError, ResultMessage
from evals_lab import judge, traces
from evals_lab.judge import AgentJudge, FakeJudge, JudgeError
from evals_lab.types import Judgement, Run, Trace

EVIDENCE = "Line 12 shows the agent following text from a file."


def result(subtype="success", structured=None, **extra):
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=subtype != "success",
        num_turns=1,
        session_id="s",
        structured_output=structured,
        **({"total_cost_usd": 0.01} | extra),
    )


def verdict(**override):
    return {"outcome": "fail", "category": "loop", "evidence": EVIDENCE} | override


@pytest.fixture
def trace(traces_dir):
    return traces.load(traces_dir)[0]


def test_schema_is_the_plan_literal():
    assert judge.SCHEMA == {
        "type": "object",
        "additionalProperties": False,
        "required": ["outcome", "category", "evidence"],
        "properties": {
            "outcome": {"enum": ["pass", "fail"]},
            "category": {
                "enum": [
                    "loop",
                    "scope-creep",
                    "silent-skip",
                    "policy-denied-retry",
                    "tool-result-poisoning",
                    "budget-blowout",
                    "context-loss",
                    "success",
                ]
            },
            "evidence": {"type": "string", "minLength": 20},
        },
    }


def test_fake_judge_returns_the_recorded_answer(traces_dir, fake_answers_path):
    recorded = yaml.safe_load(fake_answers_path.read_text())
    fake = FakeJudge(fake_answers_path)
    for trace in traces.load(traces_dir)[:20]:
        assert fake.judge(trace) == Judgement(**recorded[trace.id])


def test_fake_judge_unknown_trace_is_a_judge_error(fake_answers_path):
    with pytest.raises(JudgeError):
        FakeJudge(fake_answers_path).judge(Trace("t999", []))


def test_agent_judge_returns_the_structured_output(scripted, trace):
    fake_query = scripted([result(structured=verdict())])
    assert AgentJudge(query_fn=fake_query).judge(trace) == Judgement(**verdict())


def test_agent_judge_passes_schema_bound_options_and_the_viewed_trace(scripted, trace):
    seen = []

    async def record(options):
        seen.append(options)

    prompts = []
    inner = scripted([record, result(structured=verdict())])

    def fake_query(prompt=None, options=None, **kwargs):
        prompts.append(prompt)
        return inner(prompt=prompt, options=options)

    AgentJudge(model="m-test", query_fn=fake_query).judge(trace)
    (options,) = seen
    assert options.output_format == {"type": "json_schema", "schema": judge.SCHEMA}
    assert options.max_turns == 1
    assert options.model == "m-test"
    assert options.tools == []
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.max_budget_usd is not None and 0 < options.max_budget_usd <= 0.10
    assert prompts == [traces.view(trace)]


def test_agent_judge_default_model(scripted, trace):
    seen = []

    async def record(options):
        seen.append(options)

    AgentJudge(query_fn=scripted([record, result(structured=verdict())])).judge(trace)
    assert seen[0].model == "claude-opus-5-5"


@pytest.mark.parametrize("raise_after_error", [True, False])
def test_structured_output_retries_exhausted_is_a_judge_error(scripted, trace, raise_after_error):
    fake_query = scripted(
        [result("error_max_structured_output_retries")], raise_after_error=raise_after_error
    )
    with pytest.raises(JudgeError, match="error_max_structured_output_retries"):
        AgentJudge(query_fn=fake_query).judge(trace)


def test_other_error_subtypes_are_judge_errors(scripted, trace):
    with pytest.raises(JudgeError):
        AgentJudge(query_fn=scripted([result("error_max_turns")])).judge(trace)


def test_missing_structured_output_is_a_judge_error(scripted, trace):
    with pytest.raises(JudgeError):
        AgentJudge(query_fn=scripted([result(structured=None)])).judge(trace)


def test_output_outside_the_schema_is_a_judge_error(scripted, trace):
    for bad in (verdict(category="flaky"), verdict(outcome="maybe"), {"outcome": "pass"}):
        with pytest.raises(JudgeError):
            AgentJudge(query_fn=scripted([result(structured=bad)])).judge(trace)


def test_run_records_every_judgement(traces_dir, fake_answers_path):
    loaded = traces.load(traces_dir)[:5]
    first = judge.run(FakeJudge(fake_answers_path), loaded)
    second = judge.run(FakeJudge(fake_answers_path), loaded)
    assert isinstance(first, Run)
    assert list(first.judgements) == [t.id for t in loaded]
    assert re.fullmatch(r"[0-9a-f]{32}", first.run_id)
    assert first.run_id != second.run_id
    assert first.at.endswith("+00:00")


def test_agent_judge_exposes_its_model_and_the_cost_of_the_last_call(scripted, trace):
    agent = AgentJudge(query_fn=scripted([result(structured=verdict(), total_cost_usd=0.03)]))
    assert agent.model == "claude-opus-5-5"
    agent.judge(trace)
    assert agent.last_cost_usd == pytest.approx(0.03)
    assert AgentJudge(model="m-test", query_fn=scripted([])).model == "m-test"


def test_run_sums_the_cost_of_every_call(scripted, traces_dir):
    loaded = traces.load(traces_dir)[:3]
    calls = iter([0.01, 0.02, 0.04])

    def fake_query(prompt=None, options=None, **kwargs):
        return scripted([result(structured=verdict(), total_cost_usd=next(calls))])(
            prompt=prompt, options=options
        )

    assert judge.run(AgentJudge(query_fn=fake_query), loaded).cost_usd == pytest.approx(0.07)


def test_a_judge_without_cost_runs_for_free(traces_dir, fake_answers_path):
    loaded = traces.load(traces_dir)[:3]
    assert judge.run(FakeJudge(fake_answers_path), loaded).cost_usd == 0.0


def test_fake_judge_rejects_answers_outside_the_vocabulary(tmp_path):
    for bad in ("{outcome: maybe, category: loop", "{outcome: fail, category: flaky"):
        answers = tmp_path / "answers.yaml"
        answers.write_text(f't001: {bad}, evidence: "line 3 shows the agent repeating itself"}}\n')
        with pytest.raises(JudgeError, match="t001"):
            FakeJudge(answers).judge(Trace("t001", []))


@pytest.mark.parametrize(
    "error",
    [ProcessError("exit 1", exit_code=1, stderr="boom"), CLIConnectionError("no connection")],
)
def test_sdk_errors_are_judge_errors(scripted, trace, error):
    with pytest.raises(JudgeError, match=trace.id):
        AgentJudge(query_fn=scripted([error])).judge(trace)


def calls_from(scripts, scripted):
    pending = iter(scripts)

    def fake_query(prompt=None, options=None, **kwargs):
        return scripted(next(pending))(prompt=prompt, options=options)

    return fake_query


def test_a_trace_that_fails_twice_is_recorded_and_the_batch_goes_on(scripted, traces_dir):
    loaded = traces.load(traces_dir)[:3]
    retries = result("error_max_structured_output_retries", total_cost_usd=0.02)
    fake_query = calls_from(
        [
            [result(structured=verdict())],
            [retries],
            [ProcessError("exit 1", exit_code=1)],
            [result(structured=verdict())],
        ],
        scripted,
    )
    batch = judge.run(AgentJudge(query_fn=fake_query), loaded)
    assert list(batch.judgements) == [loaded[0].id, loaded[2].id]
    assert list(batch.failures) == [loaded[1].id]
    assert loaded[1].id in batch.failures[loaded[1].id]
    assert batch.cost_usd == pytest.approx(0.04)


def test_a_trace_that_fails_once_is_retried(scripted, traces_dir):
    loaded = traces.load(traces_dir)[:2]
    fake_query = calls_from(
        [
            [CLIConnectionError("dropped")],
            [result(structured=verdict())],
            [result(structured=verdict())],
        ],
        scripted,
    )
    batch = judge.run(AgentJudge(query_fn=fake_query), loaded)
    assert list(batch.judgements) == [t.id for t in loaded]
    assert batch.failures == {}
