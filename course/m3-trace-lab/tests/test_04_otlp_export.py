import base64
import socket
import time
from pathlib import Path

import pytest
from fake_collector import FakeCollector
from trace_lab import export
from trace_lab.cost import Prices

KEYS = {"public_key": "pk-lf-test", "secret_key": "sk-lf-test"}
BASIC = "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
BOUND_S = 10.0
RUNS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "harness-runs" / "runs"


def value_of(any_value):
    kind = any_value.WhichOneof("value")
    if kind == "array_value":
        return [value_of(v) for v in any_value.array_value.values]
    return getattr(any_value, kind)


def wire_spans(collector, requests=None):
    received = collector.received if requests is None else collector.received[:requests]
    return [
        span
        for _, request in received
        for resource_spans in request.resource_spans
        for scope_spans in resource_spans.scope_spans
        for span in scope_spans.spans
    ]


def attrs(span):
    return {kv.key: value_of(kv.value) for kv in span.attributes}


def timed_export(runs_dir, base_url, **kwargs):
    started = time.monotonic()
    summary = export.export_runs(
        runs_dir, base_url=base_url, prices=Prices.load(), **KEYS, **kwargs
    )
    return summary, time.monotonic() - started


@pytest.fixture(scope="module")
def delivered():
    with FakeCollector() as collector:
        summary, elapsed = timed_export(RUNS_DIR, collector.base_url)
    return summary, elapsed, collector


def test_headers_are_exact():
    assert export.langfuse_headers("pk-lf-miubais", "sk-lf-miubais") == {
        "Authorization": "Basic cGstbGYtbWl1YmFpczpzay1sZi1taXViYWlz",
        "x-langfuse-ingestion-version": "4",
    }


@pytest.mark.parametrize("base_url", ["http://localhost:3000", "http://localhost:3000/"])
def test_endpoint_path(base_url):
    exporter = export.langfuse_exporter(base_url, **KEYS)
    assert exporter._endpoint == "http://localhost:3000/api/public/otel/v1/traces"


def test_forty_traces_reach_the_collector(delivered):
    summary, elapsed, collector = delivered
    assert summary.traces == 40
    assert summary.failed == 0
    assert summary.failed_spans == 0
    assert elapsed < BOUND_S
    received = wire_spans(collector)
    assert len(received) == summary.spans
    assert len({span.trace_id for span in received}) == 40


def test_auth_header_on_every_request(delivered):
    _, _, collector = delivered
    assert collector.received
    for headers, _ in collector.received:
        lowered = {k.lower(): v for k, v in headers.items()}
        assert lowered["authorization"] == BASIC
        assert lowered["x-langfuse-ingestion-version"] == "4"
        assert lowered["content-type"] == "application/x-protobuf"


def test_span_names_survive_the_wire(delivered):
    _, _, collector = delivered
    names = [span.name for span in wire_spans(collector)]
    assert names.count("invoke_agent ticket-runner") == 40
    assert any(name.startswith("chat claude-") for name in names)
    assert any(name.startswith("execute_tool ") for name in names)
    assert all(name.split(" ")[0] in {"invoke_agent", "chat", "execute_tool"} for name in names)


def test_gen_ai_attributes_survive_the_wire(delivered):
    _, _, collector = delivered
    spans = wire_spans(collector)
    roots = [attrs(s) for s in spans if s.name == "invoke_agent ticket-runner"]
    assert len({r["trace_lab.ticket_id"] for r in roots}) == 10
    assert all(r["gen_ai.agent.name"] == "ticket-runner" for r in roots)
    chats = [attrs(s) for s in spans if s.name.startswith("chat ")]
    for chat in chats:
        assert chat["gen_ai.operation.name"] == "chat"
        assert chat["gen_ai.provider.name"] == "anthropic"
        assert chat["gen_ai.request.model"].startswith("claude-")
        assert isinstance(chat["gen_ai.usage.input_tokens"], int)
        assert chat["gen_ai.usage.input_tokens"] >= (
            chat["gen_ai.usage.cache_read.input_tokens"]
            + chat["gen_ai.usage.cache_creation.input_tokens"]
        )
        assert isinstance(chat["gen_ai.response.finish_reasons"], list)
        assert chat["gen_ai.usage.cost"] > 0
    tools = [attrs(s) for s in spans if s.name.startswith("execute_tool ")]
    assert tools
    for tool in tools:
        assert tool["gen_ai.operation.name"] == "execute_tool"
        assert tool["gen_ai.tool.call.id"]


def test_collector_answering_503_fails_without_raising(runs_dir):
    with FakeCollector(status=503) as collector:
        summary, elapsed = timed_export(runs_dir, collector.base_url, timeout=2.0)
    assert collector.received, "the exporter reached the collector"
    assert summary.failed > 0
    assert summary.failed_spans == summary.spans
    assert summary.traces == 40
    assert elapsed < BOUND_S


def test_spans_after_the_first_failed_batch_count_as_lost(runs_dir):
    with FakeCollector(status=503, ok_first=2) as collector:
        summary, elapsed = timed_export(runs_dir, collector.base_url, timeout=2.0)
    delivered = len(wire_spans(collector, requests=2))
    assert 0 < delivered < summary.spans
    assert summary.failed > 0
    assert summary.failed_spans == summary.spans - delivered
    assert elapsed < BOUND_S


def test_collector_not_listening_fails_without_raising(runs_dir):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    summary, elapsed = timed_export(runs_dir, f"http://127.0.0.1:{port}", timeout=2.0)
    assert summary.failed > 0
    assert summary.failed_spans == summary.spans
    assert summary.traces == 40
    assert elapsed < BOUND_S


def test_cli_prints_the_summary(runs_dir, capsys):
    with FakeCollector() as collector:
        code = export.main(
            [
                str(runs_dir),
                "--base-url",
                collector.base_url,
                "--public-key",
                "pk",
                "--secret-key",
                "sk",
            ]
        )
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("traces=40 spans=")
    assert out.strip().endswith("failed_batches=0 lost_spans=0")
