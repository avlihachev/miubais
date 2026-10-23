import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock
from harnesskit.testing import scripted_query
from miubais.paths import course_dir


@pytest.fixture
def lessons(monkeypatch):
    monkeypatch.syspath_prepend(str(course_dir() / "m1-harness-lab" / "lesson_support" / "src"))
    import harness_lab_lessons

    return harness_lab_lessons


def said(text: str, message_id: str | None = None) -> AssistantMessage:
    return AssistantMessage([TextBlock(text)], model="m", message_id=message_id)


def result(subtype: str, *, cost: float = 0.1, turns: int = 3) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=subtype != "success",
        num_turns=turns,
        session_id="sess-1",
        total_cost_usd=cost,
    )


def runs(*scripts):
    calls = []

    def query_fn(prompt, options):
        calls.append(options.resume)
        script = scripts[len(calls) - 1]
        return scripted_query([script] if isinstance(script, Exception) else script)(
            prompt, options
        )

    return query_fn, calls


def test_fresh_budget_stop_is_a_run_outcome(lessons):
    query_fn, _ = runs([said("reading"), result("error_max_budget_usd", cost=0.8)])
    run = asyncio.run(lessons.run_resuming("p", ClaudeAgentOptions(), query_fn))
    assert [a.outcome for a in run.attempts] == ["ran"]
    assert lessons.summarise_messages(run.messages, 12, 0.75).stopped_by == "budget"


def test_resumed_max_turns_after_output_is_not_rerun(lessons):
    query_fn, calls = runs([said("working"), result("error_max_turns")], [result("success")])
    run = asyncio.run(lessons.run_resuming("p", ClaudeAgentOptions(resume="old"), query_fn))
    assert calls == ["old"]
    assert run.messages[-1].subtype == "error_max_turns"


def test_error_result_before_output_is_a_failed_resume(lessons):
    query_fn, calls = runs([result("error_during_execution")], [said("x"), result("success")])
    run = asyncio.run(lessons.run_resuming("p", ClaudeAgentOptions(resume="old"), query_fn))
    assert calls == ["old", None]
    assert [a.outcome for a in run.attempts] == ["error_during_execution", "ran"]


def test_error_during_execution_is_error(lessons):
    facts = lessons.summarise_messages([said("x"), result("error_during_execution")], 12, 0.75)
    assert facts.stopped_by == "error"


def test_turns_come_from_num_turns(lessons):
    facts = lessons.summarise_messages([said("a"), said("b"), result("success", turns=9)], 12, 1)
    assert facts.turns == 9


def test_turns_without_a_result_count_distinct_message_ids(lessons):
    messages = [said("a", "msg_1"), said("b", "msg_1"), said("c", "msg_2")]
    assert lessons.summarise_messages(messages, 12, 1).turns == 2
    assert lessons.summarise_messages([said("a"), said("b")], 12, 1).turns == 2


def test_turn_count_alone_is_not_max_turns(lessons):
    messages = [said(str(i)) for i in range(12)] + [result("error_during_execution", turns=12)]
    assert lessons.summarise_messages(messages, 12, 1).stopped_by == "error"


def test_previous_cost_is_subtracted_on_resume(lessons):
    messages = [said("x"), result("success", cost=0.9)]
    assert lessons.summarise_messages(messages, 12, 0.75).stopped_by == "budget"
    facts = lessons.summarise_messages(messages, 12, 0.75, previous_cost_usd=0.4)
    assert facts.stopped_by == "success" and facts.cost_usd == pytest.approx(0.5)
