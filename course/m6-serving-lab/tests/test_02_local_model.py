import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from serving_lab import loadgen
from serving_lab.types import Summary

MODEL = "qwen3.5:0.8b"
BASE_URL = "http://localhost:11434/v1"
EXTRA_BODY = {"reasoning_effort": "none"}
REQUESTS = 8
CONCURRENCY = 2
MAX_TOKENS = 48
MIN_P50_TPS = 5
MAX_TTFT_MS = 10_000
MACHINE_CLASS = "Apple Silicon, CPU/GPU shared"
SKIP_MESSAGE = f"needs ollama model {MODEL}: run ollama pull {MODEL}"
RECORD = Path(__file__).resolve().parent.parent / "fixtures" / "live_local_model_run.json"
OLLAMA_LIST = """NAME                 ID              SIZE      MODIFIED
qwen3.5:0.8b         de63045f2975    1.3 GB    4 days ago
mistral:latest       6577803aa9a0    4.4 GB    4 months ago
"""
PROMPTS = [
    "Explain what a KV cache is in two sentences.",
    "Why does batching raise GPU throughput? Answer briefly.",
    "What does quantisation trade away? Answer in two sentences.",
    "Describe time to first token in one sentence.",
    "What is prefix caching? Keep it short.",
    "Why do requests queue on a busy inference server? Two sentences.",
    "Name two reasons to run a small model locally.",
    "What does a load generator measure? One sentence.",
]


def has_model(listing: str, model: str = MODEL) -> bool:
    rows = [line.split() for line in listing.splitlines()[1:]]
    return any(row and row[0] == model for row in rows)


def model_pulled() -> bool:
    try:
        done = subprocess.run(
            ["ollama", "list"], check=False, capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and has_model(done.stdout)


def aggregate(summary: Summary) -> dict:
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "stage": "02-local-model",
        "runtime": "ollama",
        "model": MODEL,
        "machine_class": MACHINE_CLASS,
        "requests": summary.n,
        "failed": summary.failed,
        "concurrency": CONCURRENCY,
        "max_tokens": MAX_TOKENS,
        "ttft_ms": {
            "p50": round(summary.p50_ttft_ms, 1),
            "p90": round(summary.p90_ttft_ms, 1),
            "p99": round(summary.p99_ttft_ms, 1),
        },
        "tps_p50": round(summary.p50_tps, 1),
        "throughput_tps": round(summary.throughput_tps, 1),
        "wall_s": round(summary.wall_s, 2),
        "floors": {"p50_tps": MIN_P50_TPS, "ttft_ms": MAX_TTFT_MS},
    }


def problems(summary: Summary) -> list[str]:
    found = []
    if summary.failed:
        found.append(f"{summary.failed} of {summary.n} requests failed")
    if summary.p50_tps <= MIN_P50_TPS:
        found.append(f"p50 TPS {summary.p50_tps:.1f} not above {MIN_P50_TPS}")
    if summary.p90_ttft_ms >= MAX_TTFT_MS:
        found.append(f"p90 TTFT {summary.p90_ttft_ms:.0f} ms not below {MAX_TTFT_MS}")
    return found


def save(record: dict) -> Path:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "runs" / f"live-{datetime.now(UTC).date().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def summary(**changes) -> Summary:
    base = {
        "n": 8,
        "failed": 0,
        "p50_ttft_ms": 400.0,
        "p90_ttft_ms": 900.0,
        "p99_ttft_ms": 950.0,
        "p50_tps": 80.0,
        "throughput_tps": 150.0,
        "wall_s": 3.0,
    }
    return Summary(**(base | changes))


def test_the_model_listing_is_parsed_by_name():
    assert has_model(OLLAMA_LIST)
    assert not has_model(OLLAMA_LIST, "qwen3.5:8b")
    assert not has_model(OLLAMA_LIST.replace("qwen3.5:0.8b", "x-qwen3.5:0.8b"))
    assert not has_model("")
    assert SKIP_MESSAGE == "needs ollama model qwen3.5:0.8b: run ollama pull qwen3.5:0.8b"


def test_the_load_generator_sends_the_extra_body_fields():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"choices": [{"delta": {"content": "hi"}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = loadgen.run(
            f"http://127.0.0.1:{server.server_port}/v1",
            model=MODEL,
            prompts=["a"],
            concurrency=1,
            max_tokens=MAX_TOKENS,
            extra_body=EXTRA_BODY,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert result.summary.failed == 0
    assert seen[0]["reasoning_effort"] == "none"
    assert seen[0]["model"] == MODEL and seen[0]["max_tokens"] == MAX_TOKENS


def test_the_floors_name_what_fails():
    assert problems(summary()) == []
    assert problems(summary(failed=2)) == ["2 of 8 requests failed"]
    assert problems(summary(p50_tps=5.0, p90_ttft_ms=10_000.0)) == [
        "p50 TPS 5.0 not above 5",
        "p90 TTFT 10000 ms not below 10000",
    ]


def test_the_aggregate_has_no_prompt_texts():
    record = aggregate(summary())
    assert record["ttft_ms"] == {"p50": 400.0, "p90": 900.0, "p99": 950.0}
    assert record["machine_class"] == MACHINE_CLASS
    assert all(prompt not in json.dumps(record) for prompt in PROMPTS)


def test_the_committed_record_has_exactly_the_written_fields():
    committed = json.loads(RECORD.read_text())
    written = aggregate(summary())
    assert committed.keys() == written.keys()
    assert committed["model"] == MODEL and committed["failed"] == 0
    assert committed["floors"] == written["floors"]
    assert committed["tps_p50"] > MIN_P50_TPS and committed["ttft_ms"]["p90"] < MAX_TTFT_MS


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not model_pulled(), reason=SKIP_MESSAGE)
def test_live_local_model_streams_fast_enough():
    result = loadgen.run(
        BASE_URL,
        model=MODEL,
        prompts=PROMPTS[:REQUESTS],
        concurrency=CONCURRENCY,
        max_tokens=MAX_TOKENS,
        timeout_s=120,
        extra_body=EXTRA_BODY,
    )
    record = aggregate(result.summary)
    print(f"\nlive local model: {json.dumps(record, indent=2)}")
    print(loadgen.to_markdown(result.summary))
    print(f"saved {save(record)}")
    assert problems(result.summary) == [], problems(result.summary)
