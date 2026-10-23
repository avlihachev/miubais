import json
import time

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock
from conftest import FIXTURE_EPOCH_NS
from harnesskit.testing import Timed, load_run
from opentelemetry.trace import SpanKind, StatusCode
from trace_lab import spans

CHAT_ATTRS = {
    "gen_ai.operation.name": "chat",
    "gen_ai.provider.name": "anthropic",
}


def raw(runs_dir, rid):
    return [json.loads(line) for line in (runs_dir / f"{rid}.jsonl").read_text().splitlines()]


def record(runs_dir, rid, **kwargs):
    provider, exporter = spans.provider_for_tests()
    rows = raw(runs_dir, rid)
    trace = spans.record_run(
        load_run(runs_dir / f"{rid}.jsonl"),
        ticket_id=rows[0]["ticket_id"],
        tracer_provider=provider,
        **{"epoch_ns": FIXTURE_EPOCH_NS, **kwargs},
    )
    return trace, exporter.get_finished_spans(), rows


def root_of(finished):
    [root] = [s for s in finished if s.parent is None]
    return root


def ms(span, root, attr="start_time"):
    return (getattr(span, attr) - root.start_time) / 1_000_000


def first_assistants(rows):
    seen, out = set(), []
    for i, row in enumerate(rows):
        if row["type"] == "assistant" and row["message_id"] not in seen:
            seen.add(row["message_id"])
            previous = next((r["t_ms"] for r in reversed(rows[1:i])), 0)
            out.append((row, previous))
    return out


def tool_uses(rows):
    return [
        (row, block)
        for row in rows
        if row["type"] == "assistant"
        for block in row["content"]
        if block["type"] == "tool_use"
    ]


def by_name(finished, prefix):
    return [s for s in finished if s.name.startswith(prefix)]


def test_one_span_per_turn_per_tool_call_plus_the_root(runs_dir):
    trace, finished, rows = record(runs_dir, "r001")
    turns = len({r["message_id"] for r in rows if r["type"] == "assistant"})
    records = sum(r["type"] == "assistant" for r in rows)
    assert records > turns, "r001 has parallel tool calls sharing one message_id"
    expected = turns + len(tool_uses(rows)) + 1
    assert len(finished) == expected
    assert len(trace.spans) == expected
    assert len(by_name(finished, "chat ")) == turns


def test_names_and_kinds(runs_dir):
    _, finished, rows = record(runs_dir, "r001")
    root = root_of(finished)
    assert root.name == "invoke_agent ticket-runner"
    model = rows[1]["model"]
    for span in by_name(finished, "chat "):
        assert span.name == f"chat {model}"
        assert span.kind == SpanKind.CLIENT
    tools = by_name(finished, "execute_tool ")
    assert sorted(s.name for s in tools) == sorted(
        f"execute_tool {b['name']}" for _, b in tool_uses(rows)
    )
    assert all(s.kind == SpanKind.INTERNAL for s in tools)


def test_agent_name_is_configurable(runs_dir):
    _, finished, _ = record(runs_dir, "r002", agent_name="triage")
    root = root_of(finished)
    assert root.name == "invoke_agent triage"
    assert root.attributes["gen_ai.agent.name"] == "triage"


def test_root_attributes(runs_dir):
    trace, finished, rows = record(runs_dir, "r001")
    root = root_of(finished)
    result = rows[-1]
    assert root.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert root.attributes["gen_ai.agent.name"] == "ticket-runner"
    assert root.attributes["gen_ai.conversation.id"] == rows[0]["session_id"]
    assert root.attributes["trace_lab.ticket_id"] == rows[0]["ticket_id"]
    assert root.attributes["trace_lab.cost_usd"] == result["total_cost_usd"]
    assert "error.type" not in root.attributes
    usage = result["usage"]
    assert root.attributes["gen_ai.usage.input_tokens"] == (
        usage["input_tokens"]
        + usage["cache_read_input_tokens"]
        + usage["cache_creation_input_tokens"]
    )
    assert root.attributes["gen_ai.usage.output_tokens"] == usage["output_tokens"]
    assert (
        root.attributes["gen_ai.usage.cache_read.input_tokens"]
        == (usage["cache_read_input_tokens"])
    )
    assert (
        root.attributes["gen_ai.usage.cache_creation.input_tokens"]
        == (usage["cache_creation_input_tokens"])
    )
    assert trace.ticket_id == rows[0]["ticket_id"]
    assert trace.trace_id == format(root.context.trace_id, "032x")


def test_chat_attributes_follow_the_anthropic_input_rule(runs_dir):
    _, finished, rows = record(runs_dir, "r001")
    chats = {s.attributes["gen_ai.response.id"]: s for s in by_name(finished, "chat ")}
    cached = [row for row, _ in first_assistants(rows) if row["usage"]["cache_read_input_tokens"]]
    assert cached
    for row, _ in first_assistants(rows):
        span, usage = chats[row["message_id"]], row["usage"]
        for name, value in CHAT_ATTRS.items():
            assert span.attributes[name] == value
        assert span.attributes["gen_ai.request.model"] == row["model"]
        assert span.attributes["gen_ai.response.model"] == row["model"]
        assert span.attributes["gen_ai.usage.input_tokens"] == (
            usage["input_tokens"]
            + usage["cache_read_input_tokens"]
            + usage["cache_creation_input_tokens"]
        )
        assert span.attributes["gen_ai.usage.output_tokens"] == usage["output_tokens"]
        assert (
            span.attributes["gen_ai.usage.cache_read.input_tokens"]
            == (usage["cache_read_input_tokens"])
        )
        assert (
            span.attributes["gen_ai.usage.cache_creation.input_tokens"]
            == (usage["cache_creation_input_tokens"])
        )
        assert tuple(span.attributes["gen_ai.response.finish_reasons"]) == (row["stop_reason"],)


def test_timings_come_from_t_ms(runs_dir):
    _, finished, rows = record(runs_dir, "r001")
    root = root_of(finished)
    assert ms(root, root, "end_time") == rows[-1]["t_ms"]
    chats = {s.attributes["gen_ai.response.id"]: s for s in by_name(finished, "chat ")}
    for row, previous in first_assistants(rows):
        span = chats[row["message_id"]]
        assert ms(span, root) == previous
        assert ms(span, root, "end_time") == row["t_ms"]
    tools = {s.attributes["gen_ai.tool.call.id"]: s for s in by_name(finished, "execute_tool ")}
    answered = {
        b["tool_use_id"]: r["t_ms"] for r in rows if r["type"] == "user" for b in r["content"]
    }
    for row, block in tool_uses(rows):
        span = tools[block["id"]]
        assert span.attributes["gen_ai.tool.name"] == block["name"]
        assert span.attributes["gen_ai.operation.name"] == "execute_tool"
        assert ms(span, root) == row["t_ms"]
        assert ms(span, root, "end_time") == answered[block["id"]]


def test_every_span_hangs_off_the_root(runs_dir):
    _, finished, _ = record(runs_dir, "r001")
    root = root_of(finished)
    for span in finished:
        assert span.context.trace_id == root.context.trace_id
        if span is not root:
            assert span.parent.span_id == root.context.span_id


def test_failed_tool_results_mark_the_tool_span(runs_dir):
    _, finished, rows = record(runs_dir, "r001")
    failed = {
        b["tool_use_id"] for r in rows if r["type"] == "user" for b in r["content"] if b["is_error"]
    }
    assert failed
    for span in by_name(finished, "execute_tool "):
        if span.attributes["gen_ai.tool.call.id"] in failed:
            assert span.attributes["error.type"] == "tool_error"
            assert span.status.status_code == StatusCode.ERROR
        else:
            assert "error.type" not in span.attributes


def test_truncated_run_closes_the_open_tool_span(runs_dir):
    trace, finished, rows = record(runs_dir, "r014")
    assert rows[-1]["type"] == "assistant"
    root = root_of(finished)
    assert len(finished) == len(trace.spans)
    assert all(s.end_time is not None for s in finished)
    last = rows[-1]["content"][-1]
    [open_span] = [s for s in finished if s.attributes.get("gen_ai.tool.call.id") == last["id"]]
    assert open_span.attributes["error.type"] == "no_result"
    assert open_span.end_time == root.end_time
    assert ms(root, root, "end_time") == rows[-1]["t_ms"]
    assert "trace_lab.cost_usd" not in root.attributes


def test_error_result_sets_error_type_on_the_root(runs_dir):
    _, finished, rows = record(runs_dir, "r025")
    assert rows[-1]["subtype"] == "error_max_turns"
    root = root_of(finished)
    assert root.attributes["error.type"] == "error_max_turns"
    assert root.status.status_code == StatusCode.ERROR
    assert root.attributes["trace_lab.cost_usd"] == rows[-1]["total_cost_usd"]


def test_every_recorded_run_closes_all_its_spans(runs_dir):
    for path in sorted(runs_dir.glob("*.jsonl")):
        provider, exporter = spans.provider_for_tests()
        trace = spans.record_run(
            load_run(path), ticket_id="t", tracer_provider=provider, epoch_ns=FIXTURE_EPOCH_NS
        )
        assert len(exporter.get_finished_spans()) == len(trace.spans), path.name


def test_stream_without_meta_has_no_conversation_id():
    provider, exporter = spans.provider_for_tests()
    stream = [
        Timed(
            300,
            AssistantMessage(
                content=[TextBlock(text="x"), ToolUseBlock(id="t1", name="Bash", input={})],
                model="claude-haiku-5-5",
                usage={"input_tokens": 10, "output_tokens": 3},
                message_id="m1",
                stop_reason="tool_use",
            ),
        )
    ]
    trace = spans.record_run(stream, ticket_id="009-x", tracer_provider=provider)
    finished = exporter.get_finished_spans()
    root = root_of(finished)
    assert "gen_ai.conversation.id" not in root.attributes
    assert root.attributes["trace_lab.ticket_id"] == "009-x"
    assert root.attributes["gen_ai.usage.input_tokens"] == 10
    assert len(trace.spans) == 3
    [tool] = by_name(finished, "execute_tool ")
    assert tool.attributes["error.type"] == "no_result"
    assert ms(tool, root) == ms(tool, root, "end_time") == 300


def test_spans_start_at_the_epoch_you_pass(runs_dir):
    _, finished, rows = record(runs_dir, "r001", epoch_ns=FIXTURE_EPOCH_NS + 5)
    root = root_of(finished)
    assert root.start_time == FIXTURE_EPOCH_NS + 5
    assert root.end_time == FIXTURE_EPOCH_NS + 5 + rows[-1]["t_ms"] * 1_000_000


def test_the_default_epoch_is_now(runs_dir):
    provider, exporter = spans.provider_for_tests()
    before = time.time_ns()
    spans.record_run(load_run(runs_dir / "r001.jsonl"), ticket_id="t", tracer_provider=provider)
    after = time.time_ns()
    assert before - 5 * 10**9 <= root_of(exporter.get_finished_spans()).start_time <= after
