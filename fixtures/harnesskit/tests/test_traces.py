import json
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from harnesskit.traces import TraceLine, to_trace_lines
from pydantic import ValidationError

TRACES = Path(__file__).resolve().parents[3] / "course" / "m1-harness-lab" / "fixtures" / "traces"


def test_the_m1_trace_fixtures_validate():
    files = sorted(TRACES.glob("t*.jsonl"))
    assert len(files) == 12
    for path in files:
        lines = [TraceLine.model_validate_json(raw) for raw in path.read_text().splitlines()]
        assert [line.n for line in lines] == list(range(1, len(lines) + 1)), path.name


def test_unknown_fields_and_roles_are_rejected():
    with pytest.raises(ValidationError):
        TraceLine(n=1, role="system", text="x")
    with pytest.raises(ValidationError):
        TraceLine.model_validate({"n": 1, "role": "user", "text": "x", "extra": 1})


def test_messages_become_trace_lines():
    messages = [
        SystemMessage(subtype="init", data={"session_id": "s"}),
        UserMessage(content="Ticket 001: fix rounding"),
        AssistantMessage(
            [
                ThinkingBlock(thinking="hmm", signature="sig"),
                TextBlock("Reading the pricing module."),
                ToolUseBlock("toolu_1", "Read", {"file_path": "src/p.py"}),
            ],
            model="m",
            message_id="msg_1",
        ),
        UserMessage(
            content=[ToolResultBlock("toolu_1", content=[{"type": "text", "text": "x = 1"}])]
        ),
        AssistantMessage([TextBlock("Done.")], model="m", message_id="msg_2"),
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=2,
            session_id="s",
            total_cost_usd=0.12,
        ),
    ]
    lines = [line.model_dump(exclude_none=True) for line in to_trace_lines(messages)]
    assert lines == [
        {"n": 1, "role": "user", "text": "Ticket 001: fix rounding"},
        {"n": 2, "role": "assistant", "text": "Reading the pricing module.", "message_id": "msg_1"},
        {
            "n": 3,
            "role": "assistant",
            "tool": "Read",
            "input": {"file_path": "src/p.py"},
            "message_id": "msg_1",
        },
        {"n": 4, "role": "tool", "tool": "Read", "output": "x = 1"},
        {"n": 5, "role": "assistant", "text": "Done.", "message_id": "msg_2"},
        {"n": 6, "role": "result", "subtype": "success", "cost_usd": 0.12, "num_turns": 2},
    ]


def test_trace_lines_serialise_like_the_fixtures():
    line = TraceLine(n=1, role="tool", tool="Bash", output="ok")
    assert json.loads(line.model_dump_json(exclude_none=True)) == {
        "n": 1,
        "role": "tool",
        "tool": "Bash",
        "output": "ok",
    }


def test_string_tool_result_and_unknown_tool_id():
    messages = [UserMessage(content=[ToolResultBlock("toolu_9", content="plain output")])]
    assert to_trace_lines(messages)[0].model_dump(exclude_none=True) == {
        "n": 1,
        "role": "tool",
        "output": "plain output",
    }
