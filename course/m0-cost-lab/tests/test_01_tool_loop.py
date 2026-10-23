import json

import pytest
from cost_lab.loop import RefusalError, TruncatedError, run_tool_loop

SKU_SCHEMA = {
    "type": "object",
    "properties": {"sku": {"type": "string"}},
    "required": ["sku"],
    "additionalProperties": False,
}
TOOLS = [
    {"name": "get_price", "description": "Price of a SKU", "input_schema": SKU_SCHEMA},
    {"name": "get_stock", "description": "Stock of a SKU", "input_schema": SKU_SCHEMA},
]
COMMON = {
    "model": "claude-opus-5-5",
    "max_tokens": 1000,
    "system": "s",
    "tools": TOOLS,
    "messages": [{"role": "user", "content": "A1?"}],
}


def body(fixture_dir, name):
    return json.loads((fixture_dir / f"{name}.json").read_text())["body"]


def tool_use_ids(content):
    return [b["id"] for b in content if b["type"] == "tool_use"]


def final_text(fixture_dir, name):
    return "".join(b["text"] for b in body(fixture_dir, name)["content"] if b["type"] == "text")


def test_loop_returns_all_tool_results_in_one_user_message(client_for, fixture_dir):
    client, t = client_for(["loop_turn1", "loop_turn2"])
    turn1, turn2 = body(fixture_dir, "loop_turn1"), body(fixture_dir, "loop_turn2")
    calls = []

    def execute(name, args):
        calls.append((name, args))
        return {"get_price": "12.50", "get_stock": "7"}[name]

    r = run_tool_loop(client, execute=execute, **COMMON)
    assert r.final_text == final_text(fixture_dir, "loop_turn2") and r.turns == 2
    asked = [(b["name"], b["input"]) for b in turn1["content"] if b["type"] == "tool_use"]
    assert calls == asked
    second = t.requests[1].body["messages"]
    assert second[-2] == {"role": "assistant", "content": turn1["content"]}
    assert second[-1]["role"] == "user"
    results = second[-1]["content"]
    assert [b["tool_use_id"] for b in results] == tool_use_ids(turn1["content"])
    assert all(b["type"] == "tool_result" for b in results)
    for field in ("input_tokens", "output_tokens"):
        assert getattr(r.usage, field) == turn1["usage"][field] + turn2["usage"][field]


def test_tool_error_is_reported_not_raised(client_for, fixture_dir):
    client, t = client_for(["loop_turn1", "loop_turn2"])
    failing_id = tool_use_ids(body(fixture_dir, "loop_turn1")["content"])[1]

    def execute(name, args):
        if name == "get_stock":
            raise RuntimeError("stock service down")
        return "12.50"

    r = run_tool_loop(client, execute=execute, **COMMON)
    assert r.final_text == final_text(fixture_dir, "loop_turn2")
    results = t.requests[1].body["messages"][-1]["content"]
    ok, failed = results
    assert not ok.get("is_error")
    assert failed["tool_use_id"] == failing_id and failed["is_error"] is True
    assert "stock service down" in failed["content"]


def test_truncated_response_raises(client_for, fixture_dir):
    client, _ = client_for(["loop_truncated"])
    with pytest.raises(TruncatedError) as e:
        run_tool_loop(client, execute=lambda n, a: "", **COMMON)
    assert e.value.partial_text == final_text(fixture_dir, "loop_truncated")


def test_max_turns_exceeded_raises(client_for):
    client, t = client_for(["loop_turn1", "loop_turn1", "loop_turn1"])
    with pytest.raises(RuntimeError, match="max_turns"):
        run_tool_loop(client, execute=lambda n, a: "x", max_turns=2, **COMMON)
    assert len(t.requests) == 2


def test_refusal_raises_with_the_category(client_for, fixture_dir):
    client, _ = client_for(["loop_refusal"])
    with pytest.raises(RefusalError) as e:
        run_tool_loop(client, execute=lambda n, a: "", **COMMON)
    assert e.value.category == body(fixture_dir, "loop_refusal")["stop_details"]["category"]


def test_pause_turn_is_resent_with_the_paused_content(client_for, fixture_dir):
    client, t = client_for(["loop_pause", "loop_turn2"])
    r = run_tool_loop(client, execute=lambda n, a: "", **COMMON)
    assert r.final_text == final_text(fixture_dir, "loop_turn2") and r.turns == 2
    resent = t.requests[1].body["messages"]
    assert resent[:-1] == COMMON["messages"]
    assert resent[-1] == {
        "role": "assistant",
        "content": body(fixture_dir, "loop_pause")["content"],
    }
