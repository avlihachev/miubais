import base64

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage
from harnesskit.testing import Timed, load_run
from miubais.paths import course_dir, repo_root


@pytest.fixture
def lessons(monkeypatch):
    monkeypatch.syspath_prepend(str(course_dir() / "m3-trace-lab" / "lesson_support" / "src"))
    import trace_lab_lessons

    return trace_lab_lessons


def assistant(message_id, *blocks):
    return AssistantMessage(
        content=list(blocks), model="claude-sonnet-5-5", message_id=message_id, usage={}
    )


def result(tool_id, is_error=False):
    return UserMessage(content=[ToolResultBlock(tool_id, "ok", is_error)])


def test_parallel_tool_calls_make_one_chat_span(lessons):
    timed = [
        Timed(0, {"type": "meta"}),
        Timed(100, assistant("m1", ToolUseBlock("t1", "Read", {}))),
        Timed(100, assistant("m1", ToolUseBlock("t2", "Grep", {}))),
        Timed(150, result("t1")),
        Timed(400, result("t2", is_error=True)),
        Timed(900, assistant("m2", TextBlock("done"))),
    ]
    nodes = lessons.span_tree(timed)
    assert [n.name for n in nodes] == [
        "invoke_agent ticket-runner",
        "chat claude-sonnet-5-5",
        "execute_tool Read",
        "execute_tool Grep",
        "chat claude-sonnet-5-5",
    ]
    assert [n.duration_ms for n in nodes] == [900, 100, 50, 300, 500]
    assert nodes[3].error == "tool_error"
    assert all(n.parent == "invoke_agent ticket-runner" for n in nodes[1:])


def test_a_tool_without_result_is_closed_with_no_result(lessons):
    timed = [
        Timed(10, assistant("m1", ToolUseBlock("t1", "Bash", {}))),
        Timed(10, assistant("m1", ToolUseBlock("t2", "Read", {}))),
        Timed(70, result("t2")),
    ]
    nodes = lessons.span_tree(timed)
    bash = next(n for n in nodes if n.name == "execute_tool Bash")
    assert (bash.end_ms, bash.error) == (70, "no_result")


def test_span_count_on_a_recorded_run(lessons):
    nodes = lessons.span_tree(load_run(repo_root() / "fixtures/harness-runs/runs/r018.jsonl"))
    assert len(nodes) == 12
    assert "execute_tool Grep" in lessons.render_tree(nodes)


def test_anthropic_input_rule_adds_both_cache_parts(lessons):
    usage = {"input_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20}
    assert lessons.anthropic_input_tokens(usage) == 125
    assert lessons.anthropic_input_tokens({}) == 0


def test_inference_attributes_use_the_installed_constant_names(lessons):
    usage = {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3}
    attrs = lessons.inference_attributes("m", usage, finish_reason="end_turn")
    assert attrs["gen_ai.usage.input_tokens"] == 4
    assert attrs["gen_ai.usage.cache_creation.input_tokens"] == 0
    assert attrs["gen_ai.provider.name"] == "anthropic"
    assert attrs["gen_ai.response.finish_reasons"] == ["end_turn"]
    assert "gen_ai.response.id" not in attrs


def test_langfuse_headers_and_urls(lessons):
    headers = lessons.langfuse_headers("pk", "sk")
    assert base64.b64decode(headers["Authorization"].removeprefix("Basic ")) == b"pk:sk"
    assert headers["x-langfuse-ingestion-version"] == "4"
    assert (
        lessons.otlp_traces_endpoint("http://h:3000/") == "http://h:3000/api/public/otel/v1/traces"
    )
    assert lessons.observations_url("http://h:3000", "abc", 5) == (
        "http://h:3000/api/public/v2/observations?traceId=abc&limit=5"
    )


def usage(input_tokens=0, output=0, read=0, write=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output,
        "cache_read_input_tokens": read,
        "cache_creation_input_tokens": write,
    }


PRICES = {"m": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write_5m": 5.0}}


def priced(message_id, use, *blocks):
    return AssistantMessage(content=list(blocks), model="m", message_id=message_id, usage=use)


def test_message_cost_prices_each_token_kind(lessons):
    cost = lessons.message_cost("m", usage(1_000_000, 1_000_000, 1_000_000, 1_000_000), PRICES)
    assert cost == pytest.approx(4.0 + 20.0 + 0.2 + 5.0)


def test_run_cost_counts_a_shared_message_id_once(lessons):
    use = usage(100, 10, 800, 100)
    timed = [
        Timed(0, {"type": "meta", "ticket_id": "t1"}),
        Timed(5, priced("m1", use, ToolUseBlock("a", "Read", {}))),
        Timed(5, priced("m1", use, ToolUseBlock("b", "Grep", {}))),
    ]
    cost = lessons.run_cost(timed, PRICES)
    assert cost.ticket_id == "t1"
    assert cost.usd == pytest.approx(lessons.message_cost("m", use, PRICES))
    assert cost.cache_hit_ratio == pytest.approx(0.8)
    assert cost.reported_usd is None


def test_cost_summary_over_the_recorded_runs_reconciles(lessons):
    prices = lessons.load_prices(repo_root() / "fixtures/harness-runs/prices.json")
    paths = sorted((repo_root() / "fixtures/harness-runs/runs").glob("r*.jsonl"))
    summary = lessons.cost_summary([lessons.run_cost(load_run(p), prices) for p in paths])
    assert (summary["runs"], summary["tickets"], summary["runs_with_result"]) == (40, 10, 38)
    assert summary["max_reconcile_delta"] < 1e-9
    assert 0.25 < summary["top_quartile_run_share"] < 1.0


def test_top_share_and_percentile(lessons):
    assert lessons.top_share([1.0, 1.0, 1.0, 5.0]) == pytest.approx(5 / 8)
    assert lessons.top_share([]) == 0.0
    values = list(range(1, 101))
    assert [lessons.percentile(values, q) for q in (50, 90, 99, 100)] == [50, 90, 99, 100]
    assert lessons.percentile([7], 50) == 7
    with pytest.raises(ValueError):
        lessons.percentile([], 50)


def test_router_falls_back_on_max_turns_but_not_on_policy(lessons):
    routes = [
        lessons.Route("cheap", "haiku", 0.1, 5),
        lessons.Route("strong", "sonnet", 0.5, 10),
    ]
    router = lessons.LessonRouter(routes)
    outcomes = {
        ("a", "haiku"): lessons.Outcome("max_turns", 0.05, 5),
        ("a", "sonnet"): lessons.Outcome("success", 0.20, 4),
        ("b", "haiku"): lessons.Outcome("policy", 0.01, 1),
    }

    def run_fn(ticket, *, model, max_turns, max_budget_usd):
        return outcomes[(ticket, model)]

    assert router.run("a", run_fn)[0] == "strong"
    final, attempts = router.run("b", run_fn)
    assert (final, len(attempts)) == ("cheap", 1)
    assert router.stats["cheap"].attempts == 2
    assert router.stats["strong"].successes == 1
    assert "0.2000" in router.table()
    with pytest.raises(ValueError):
        lessons.LessonRouter(routes, fallback_on=frozenset({"policy"}))


def test_tool_latency_table_leaves_out_unfinished_calls(lessons):
    timed = [
        Timed(0, assistant("m1", ToolUseBlock("t1", "Read", {}))),
        Timed(0, assistant("m1", ToolUseBlock("t2", "Bash", {}))),
        Timed(40, result("t1")),
        Timed(90, assistant("m2", ToolUseBlock("t3", "Read", {}))),
        Timed(150, result("t3")),
    ]
    spans = lessons.tool_durations(timed)
    assert [s.duration_ms for s in spans] == [40, 150, 60]
    table = lessons.tool_latency_table(spans)
    assert "Read      2     40     60     60     60" in table
    assert "Bash" not in table
    assert table.endswith("unfinished (no_result, left out): 1")
    assert lessons.parallel_turns(timed) == (1, 2)
