from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from harnesskit.testing import scripted_query


def assistant(*blocks, model="claude-opus-5-5", message_id=None):
    return AssistantMessage(content=list(blocks), model=model, message_id=message_id)


def text(value):
    return TextBlock(text=value)


def tool_use(id, name, input):
    return ToolUseBlock(id=id, name=name, input=input)


def result(subtype="success", *, turns=1, cost=0.01, session_id="sess-1", text=None, **extra):
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=subtype != "success",
        num_turns=turns,
        session_id=session_id,
        total_cost_usd=cost,
        result=text,
        **extra,
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")


@pytest.fixture
def fixture_dir():
    return Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def scripted():
    return scripted_query


def recorder(*runs):
    calls = []

    def query_fn(prompt=None, options=None):
        calls.append((prompt, options))
        run = runs[len(calls) - 1]
        return scripted_query([run] if isinstance(run, BaseException) else run)(prompt, options)

    return query_fn, calls


@pytest.fixture
def hook_event():
    def build(tool_name, tool_input, event="PreToolUse", cwd="/work"):
        return {
            "hook_event_name": event,
            "session_id": "sess-1",
            "cwd": cwd,
            "tool_name": tool_name,
            "tool_input": tool_input,
        }

    return build
