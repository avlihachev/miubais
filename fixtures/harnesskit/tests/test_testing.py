import asyncio
import json

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ProcessError,
    ResultError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from harnesskit.testing import Timed, dump_run, load_run, scripted_query


def result(subtype: str, *, errors=None, is_error=None) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=subtype != "success" if is_error is None else is_error,
        num_turns=2,
        session_id="sess-1",
        total_cost_usd=0.1,
        errors=errors,
    )


def drain(query, seen):
    async def go():
        async for message in query(prompt="p", options=None):
            seen.append(message)

    asyncio.run(go())


def test_success_yields_everything_and_ends_quietly():
    said = AssistantMessage(content=[TextBlock(text="hi")], model="m")
    seen = []
    drain(scripted_query([said, result("success")]), seen)
    assert [type(m) for m in seen] == [AssistantMessage, ResultMessage]


@pytest.mark.parametrize("subtype", ["error_max_turns", "error_max_budget_usd"])
def test_error_result_is_yielded_then_raised_like_the_sdk(subtype):
    seen = []
    with pytest.raises(ResultError) as info:
        drain(scripted_query([result(subtype)]), seen)
    assert [m.subtype for m in seen] == [subtype]
    err = info.value
    assert isinstance(err, ProcessError) and err.exit_code == 1
    assert err.subtype == subtype and err.session_id == "sess-1"
    assert err.data["type"] == "result" and err.data["num_turns"] == 2
    assert str(err).startswith(f"Claude Code returned an error result: {subtype}")


def test_raises_on_is_error_not_on_subtype():
    with pytest.raises(ResultError):
        drain(scripted_query([result("success", is_error=True)]), [])
    seen = []
    drain(scripted_query([result("error_max_turns", is_error=False)]), seen)
    assert [m.subtype for m in seen] == ["error_max_turns"]


def test_error_text_prefers_errors_list():
    with pytest.raises(ResultError, match="No conversation found"):
        drain(
            scripted_query([result("error_during_execution", errors=["No conversation found"])]), []
        )


def test_raise_after_error_can_be_turned_off():
    seen = []
    drain(scripted_query([result("error_max_turns")], raise_after_error=False), seen)
    assert len(seen) == 1


def test_exceptions_and_steps_in_the_script():
    calls = []

    async def step(options):
        calls.append(options)

    query = scripted_query([step, RuntimeError("cli missing")])
    with pytest.raises(RuntimeError, match="cli missing"):
        asyncio.run(_consume(query("p", "opts")))
    assert calls == ["opts"]


async def _consume(messages):
    async for _ in messages:
        pass


def test_each_call_replays_from_the_start():
    query = scripted_query([result("success")])
    first, second = [], []
    drain(query, first)
    drain(query, second)
    assert len(first) == len(second) == 1


def sample_run():
    return [
        Timed(0, {"type": "meta", "ticket_id": "001-x", "session_id": "s-1"}),
        Timed(
            120,
            AssistantMessage(
                content=[
                    TextBlock(text="look"),
                    ToolUseBlock(id="t1", name="Read", input={"p": 1}),
                ],
                model="claude-opus-5-5",
                usage={"input_tokens": 5, "output_tokens": 2},
                message_id="m1",
                stop_reason="tool_use",
            ),
        ),
        Timed(
            400,
            UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok", is_error=False)]),
        ),
        Timed(
            900,
            ResultMessage(
                subtype="success",
                duration_ms=900,
                duration_api_ms=700,
                is_error=False,
                num_turns=1,
                session_id="s-1",
                total_cost_usd=0.01,
                usage={"input_tokens": 5},
                model_usage={"claude-opus-5-5": {"costUSD": 0.01}},
            ),
        ),
    ]


def test_dump_then_load_round_trips(tmp_path):
    path = tmp_path / "run.jsonl"
    dump_run(path, sample_run())
    assert load_run(path) == sample_run()
    first = json.loads(path.read_text().splitlines()[0])
    assert first == {"t_ms": 0, "type": "meta", "ticket_id": "001-x", "session_id": "s-1"}


def test_load_run_derives_is_error_from_subtype(tmp_path):
    path = tmp_path / "run.jsonl"
    record = {
        "t_ms": 5,
        "type": "result",
        "subtype": "error_max_turns",
        "num_turns": 3,
        "session_id": "s",
        "duration_ms": 5,
        "duration_api_ms": 4,
    }
    path.write_text(json.dumps(record) + "\n")
    [item] = load_run(path)
    assert item.at_ms == 5 and item.message.is_error is True


def test_system_string_user_and_thinking_round_trip(tmp_path):
    path = tmp_path / "run.jsonl"
    timed = [
        Timed(0, SystemMessage(subtype="init", data={"type": "system", "model": "m"})),
        Timed(5, UserMessage(content="plain prompt")),
        Timed(
            9,
            AssistantMessage(
                content=[ThinkingBlock(thinking="hmm", signature="sig"), TextBlock(text="ok")],
                model="claude-opus-5-5",
                message_id="m1",
            ),
        ),
    ]
    dump_run(path, timed)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0] == {
        "t_ms": 0,
        "type": "system",
        "subtype": "init",
        "data": {"type": "system", "model": "m"},
    }
    assert records[1]["content"] == "plain prompt"
    assert records[2]["content"][0] == {"type": "thinking", "thinking": "hmm", "signature": "sig"}
    assert load_run(path) == timed
