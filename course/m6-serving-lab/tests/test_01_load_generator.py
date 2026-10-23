import json
import threading
import time
import urllib.request

import httpx2
import pytest
from serving_lab import loadgen
from serving_lab.types import RequestResult

MODEL = "fake-7b"
TOLERANCE = 0.2


def prompts(n: int) -> list[str]:
    return [f"prompt number {i}" for i in range(n)]


def metrics(server) -> dict[str, float]:
    with urllib.request.urlopen(f"{server.url}/metrics", timeout=5) as response:
        text = response.read().decode()
    values = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, value = line.rsplit(" ", 1)
            values[name.split("{", 1)[0]] = float(value)
    return values


def run(server, n: int, *, concurrency: int = 1, max_tokens: int = 10):
    return loadgen.run(
        server.base_url,
        model=MODEL,
        prompts=prompts(n),
        concurrency=concurrency,
        max_tokens=max_tokens,
        timeout_s=30,
    )


@pytest.mark.parametrize(
    ("p", "expected"), [(5, 15), (30, 20), (40, 20), (50, 35), (90, 50), (100, 50)]
)
def test_percentile_is_nearest_rank(p, expected):
    assert loadgen.percentile([35, 20, 50, 15, 40], p) == expected


def test_percentile_on_a_hundred_values_and_on_none():
    values = [float(v) for v in range(100, 0, -1)]
    assert loadgen.percentile(values, 50) == 50
    assert loadgen.percentile(values, 90) == 90
    assert loadgen.percentile(values, 99) == 99
    assert loadgen.percentile([], 50) == 0.0


def test_summary_ignores_failed_requests_in_percentiles_and_throughput():
    requests = [
        RequestResult(0, 100.0, 40.0, 500.0, 20, True),
        RequestResult(1, 300.0, 60.0, 700.0, 20, True),
        RequestResult(2, 5.0, None, 10.0, 3, False, "stream closed"),
    ]
    summary = loadgen.summarise(requests, wall_s=2.0)
    assert (summary.n, summary.failed) == (3, 1)
    assert summary.p50_ttft_ms == 100.0
    assert summary.p90_ttft_ms == 300.0
    assert summary.p99_ttft_ms == 300.0
    assert summary.p50_tps == 40.0
    assert summary.throughput_tps == pytest.approx(20.0)
    assert summary.wall_s == 2.0


def test_ttft_is_queue_delay_plus_first_token_delay(fake_server):
    server = fake_server(queue_delay_ms=200, first_token_ms=100, tokens_per_second=100)
    result = run(server, 3)
    assert all(r.ok for r in result.requests), result.requests
    for r in result.requests:
        assert r.ttft_ms == pytest.approx(300, rel=TOLERANCE)
        assert r.latency_ms >= r.ttft_ms
    assert result.summary.p50_ttft_ms == pytest.approx(300, rel=TOLERANCE)


def test_tps_matches_the_configured_token_rate(fake_server):
    server = fake_server(tokens_per_second=40, first_token_ms=20)
    result = run(server, 2, max_tokens=40)
    assert all(r.ok and r.output_tokens == 40 for r in result.requests), result.requests
    for r in result.requests:
        assert r.tps == pytest.approx(40, rel=TOLERANCE)
    assert result.summary.p50_tps == pytest.approx(40, rel=TOLERANCE)
    assert result.summary.throughput_tps == pytest.approx(80 / result.summary.wall_s)


def test_role_only_delta_is_not_the_first_token(fake_server):
    server = fake_server(first_token_ms=300, tokens_per_second=100)
    result = run(server, 1, max_tokens=3)
    (r,) = result.requests
    assert r.ok
    assert r.ttft_ms >= 300 * (1 - TOLERANCE)


def test_done_sentinel_and_role_delta_are_not_counted_as_tokens(fake_server):
    server = fake_server(first_token_ms=10, tokens_per_second=200)
    result = run(server, 2, max_tokens=5)
    assert [r.output_tokens for r in result.requests] == [5, 5]
    assert all(r.ok and r.error is None for r in result.requests)


def test_stream_closed_without_done_is_a_failure(fake_server):
    server = fake_server(first_token_ms=10, tokens_per_second=200, fail_after_tokens=3)
    result = run(server, 2, max_tokens=10)
    for r in result.requests:
        assert r.ok is False
        assert r.error == "stream closed"
    assert result.summary.failed == 2
    assert result.summary.throughput_tps == 0.0


def test_http_error_is_a_failure_with_the_status(fake_server):
    server = fake_server()
    result = loadgen.run(
        server.base_url, model="no-such-model", prompts=prompts(1), concurrency=1, max_tokens=4
    )
    (r,) = result.requests
    assert (r.ok, r.error, r.output_tokens) == (False, "HTTP 404", 0)


def test_concurrency_above_server_slots_raises_p90_ttft(fake_server):
    server = fake_server(max_concurrent=2, first_token_ms=50, tokens_per_second=100)
    within = run(server, 8, concurrency=2, max_tokens=15)
    seen = {"waiting": 0.0, "running": 0.0}
    done = threading.Event()

    def poll():
        while not done.is_set():
            m = metrics(server)
            seen["waiting"] = max(seen["waiting"], m["vllm:num_requests_waiting"])
            seen["running"] = max(seen["running"], m["vllm:num_requests_running"])
            time.sleep(0.02)

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    try:
        over = run(server, 8, concurrency=8, max_tokens=15)
    finally:
        done.set()
        poller.join(timeout=5)
    assert within.summary.failed == over.summary.failed == 0
    assert over.summary.p90_ttft_ms > 2 * within.summary.p90_ttft_ms
    assert seen["waiting"] >= 1
    assert seen["running"] <= 2


def test_server_metrics_count_every_request(fake_server):
    server = fake_server(first_token_ms=10, tokens_per_second=200)
    run(server, 3, concurrency=3, max_tokens=4)
    m = metrics(server)
    assert m["vllm:e2e_request_latency_seconds_count"] == 3
    assert m["vllm:time_to_first_token_seconds_count"] == 3
    assert m["vllm:num_requests_running"] == 0
    assert m["vllm:num_requests_waiting"] == 0
    assert m["vllm:prefix_cache_queries_total"] > 0


def test_non_streaming_completion(fake_server):
    server = fake_server(first_token_ms=10, tokens_per_second=200)
    body = {"model": MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 3}
    response = httpx2.post(f"{server.base_url}/chat/completions", json=body, timeout=10)
    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "tok1 tok2 tok3"
    assert payload["usage"]["completion_tokens"] == 3


def test_to_markdown_has_every_metric():
    summary = loadgen.summarise([RequestResult(0, 120.0, 45.0, 900.0, 30, True)], wall_s=1.5)
    text = loadgen.to_markdown(summary)
    assert text.startswith("| metric | value |")
    for label in ("requests", "failed", "TTFT p50", "TTFT p90", "TTFT p99", "TPS p50"):
        assert label in text
    assert "throughput" in text and "wall time" in text
    assert "120.0" in text and "20.0" in text


def test_cli_prints_a_table_and_writes_json(fake_server, tmp_path, capsys):
    server = fake_server(first_token_ms=10, tokens_per_second=500)
    out = tmp_path / "run.json"
    argv = ["--base-url", server.base_url, "--model", MODEL, "--concurrency", "4"]
    argv += ["--requests", "6", "--max-tokens", "8", "--out", str(out)]
    assert loadgen.main(argv) == 0
    assert "TTFT p50" in capsys.readouterr().out
    data = json.loads(out.read_text())
    assert data["summary"]["n"] == 6
    assert len(data["requests"]) == 6
    assert all(r["output_tokens"] == 8 for r in data["requests"])
