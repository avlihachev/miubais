import json
from types import SimpleNamespace

import pytest
from cost_lab.prefix import build_request, cache_report, prefix_bytes

M = "claude-opus-5-5"
SYS = "You are a pricing assistant."
SCHEMA = {"type": "object", "properties": {"sku": {"type": "string"}}, "required": ["sku"]}
T1 = {"name": "get_price", "description": "Price", "input_schema": SCHEMA}
T2 = {"name": "get_stock", "description": "Stock", "input_schema": SCHEMA}
EPHEMERAL = {"type": "ephemeral"}
PREFIX_KEYS = ("model", "tools", "system")


def make(user_turn="first", tools=(T2, T1), **kw):
    return build_request(
        model=M,
        max_tokens=100,
        system_static=SYS,
        tools=list(tools),
        history=[],
        user_turn=user_turn,
        **kw,
    )


def test_prefix_is_byte_identical_across_user_turns():
    a = make("first", tools=[T2, T1])
    b = make("second", tools=[T1, T2])
    assert prefix_bytes(a) == prefix_bytes(b)
    assert a["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in a["tools"]] == sorted(t["name"] for t in [T1, T2])


def test_prefix_ignores_nested_schema_key_order():
    reordered = {
        "required": ["sku"],
        "properties": {"sku": {"type": "string"}},
        "type": "object",
    }
    other = {**T1, "input_schema": reordered}
    assert prefix_bytes(make(tools=[T1, T2])) == prefix_bytes(make(tools=[other, T2]))


def test_tool_keys_are_sorted_recursively():
    a = make(tools=[{"input_schema": {"type": "object", "properties": {}}, "name": "x"}])
    assert list(a["tools"][0]) == ["input_schema", "name"]
    assert list(a["tools"][0]["input_schema"]) == ["properties", "type"]


def test_one_hour_ttl_goes_into_cache_control():
    a = make(ttl="1h")
    assert a["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_history_is_kept_and_user_turn_appended():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    a = build_request(
        model=M, max_tokens=100, system_static=SYS, tools=[], history=history, user_turn="next"
    )
    assert a["messages"] == [*history, {"role": "user", "content": "next"}]
    assert history == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]


def breakpoint_problems(params):
    problems = []
    if any("cache_control" in tool for tool in params.get("tools", [])):
        problems.append("cache_control on a tool, before the system block")
    system = params.get("system")
    if not isinstance(system, list) or not system or "cache_control" not in system[-1]:
        problems.append("no cache_control on the last system block")
    elif any("cache_control" in block for block in system[:-1]):
        problems.append("cache_control on a system block before the last one")
    messages = params.get("messages", [])
    marked = [
        (i, j)
        for i, message in enumerate(messages)
        if isinstance(message["content"], list)
        for j, block in enumerate(message["content"])
        if "cache_control" in block
    ]
    trailing = (len(messages) - 1, len(messages[-1]["content"]) - 1) if messages else None
    if len(marked) > 1 or (marked and marked[0] != trailing):
        problems.append("cache_control in messages other than the last block of the last message")
    return problems


def wire_prefix(body):
    subset = {k: body[k] for k in PREFIX_KEYS if k in body}
    return json.dumps(subset, separators=(",", ":"), ensure_ascii=False).encode()


def system_blocks(*texts, marked=()):
    return [
        {"type": "text", "text": text, **({"cache_control": EPHEMERAL} if i in marked else {})}
        for i, text in enumerate(texts)
    ]


def test_only_breakpoint_is_on_the_last_system_block():
    assert breakpoint_problems(make()) == []
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    a = build_request(
        model=M, max_tokens=100, system_static=SYS, tools=[T1], history=history, user_turn="x"
    )
    assert breakpoint_problems(a) == []


def test_one_trailing_breakpoint_on_the_last_message_is_allowed():
    turn = {"type": "text", "text": "next", "cache_control": EPHEMERAL}
    params = {
        "tools": [T1],
        "system": system_blocks(SYS, marked=(0,)),
        "messages": [{"role": "user", "content": "hi"}, {"role": "user", "content": [turn]}],
    }
    assert breakpoint_problems(params) == []


def test_breakpoint_that_covers_a_volatile_block_is_rejected():
    stamped = system_blocks("Now: 2026-10-17T14:03:11Z", SYS, marked=(0, 1))
    assert breakpoint_problems({"system": stamped, "messages": []})
    varying_system = system_blocks("Now: 2026-10-17T14:03:11Z", marked=())
    tool = {**T1, "cache_control": EPHEMERAL}
    assert breakpoint_problems({"tools": [tool], "system": varying_system, "messages": []})
    early = {"role": "user", "content": [{"type": "text", "text": "a", "cache_control": EPHEMERAL}]}
    late = {"role": "user", "content": [{"type": "text", "text": "b"}]}
    params = {"system": system_blocks(SYS, marked=(0,)), "messages": [early, late]}
    assert breakpoint_problems(params)


def test_prefix_bytes_change_when_system_text_changes():
    changed = build_request(
        model=M, max_tokens=100, system_static=SYS + "!", tools=[T1, T2], history=[], user_turn="x"
    )
    assert prefix_bytes(make()) != prefix_bytes(changed)


def test_prefix_bytes_change_when_tool_order_changes():
    a = make()
    swapped = {**a, "tools": list(reversed(a["tools"]))}
    assert prefix_bytes(a) != prefix_bytes(swapped)


def test_prefix_bytes_equal_the_prefix_the_transport_recorded(client_for):
    client, t = client_for(["cache_write"])
    params = make()
    client.messages.create(**params)
    assert prefix_bytes(params) == wire_prefix(t.requests[0].body)


def test_cache_report_sums_and_ratio():
    r = cache_report(
        SimpleNamespace(
            input_tokens=42, cache_creation_input_tokens=0, cache_read_input_tokens=1800
        )
    )
    assert r.total_prompt == 1842 and r.hit_ratio == pytest.approx(1800 / 1842)
    assert r.read == 1800 and r.written == 0 and r.uncached == 42


def test_cache_report_empty_usage_has_zero_ratio():
    r = cache_report(
        SimpleNamespace(input_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    )
    assert r.total_prompt == 0 and r.hit_ratio == 0


def test_cache_report_treats_none_fields_as_zero():
    r = cache_report(
        SimpleNamespace(
            input_tokens=10, cache_creation_input_tokens=None, cache_read_input_tokens=None
        )
    )
    assert r.total_prompt == 10 and r.read == 0 and r.written == 0 and r.hit_ratio == 0


def recorded_usage(fixture_dir, name):
    return json.loads((fixture_dir / f"{name}.json").read_text())["body"]["usage"]


def test_second_identical_request_reads_cache(client_for, fixture_dir):
    client, t = client_for(["cache_write", "cache_read"])
    params = make()
    first = client.messages.create(**params)
    second = client.messages.create(**params)
    written = recorded_usage(fixture_dir, "cache_write")["cache_creation_input_tokens"]
    read = recorded_usage(fixture_dir, "cache_read")["cache_read_input_tokens"]
    assert written > 0 and read > 0
    assert cache_report(first.usage).written == written
    assert cache_report(second.usage).read == read
    a, b = (r.body for r in t.requests)
    assert a["system"] == b["system"] and a["tools"] == b["tools"]
