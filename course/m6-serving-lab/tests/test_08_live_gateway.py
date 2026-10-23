import json
import math
import os
import socket
import subprocess
import threading
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from harnesskit.testing import scripted_query
from serving_lab import gateway
from serving_lab.types import ChatRequest, ChatResult, Route

LOCAL_MODEL = "qwen3.5:0.8b"
API_MODEL = "claude-opus-5-5"
BASE_URL = "http://localhost:11434/v1"
HEALTH_PATH = "/"
EXTRA_BODY = {"reasoning_effort": "none"}
LOCAL = "ollama"
API = "claude"
LOCAL_CONTEXT = 1024
API_CONTEXT = 200_000
API_IN, API_OUT = 4.0, 20.0
MAX_TOKENS = 128
TIMEOUT_S = 120.0
BUDGET_USD = 0.20
SKIP_MESSAGE = f"needs ollama model {LOCAL_MODEL}: run ollama pull {LOCAL_MODEL}"
RECORD = Path(__file__).resolve().parent.parent / "fixtures" / "live_gateway_run.json"
LOG = "\n".join(
    f"12:{i // 60:02d}:{i % 60:02d} worker-{i % 4} request {1000 + i} took {120 + i % 7 * 45} ms"
    + (" status 503 upstream timeout" if i % 9 == 0 else " status 200")
    for i in range(80)
)
PLAN = [
    ("local-1", "local", "In one sentence, what is a KV cache?", LOCAL),
    ("local-2", "local", "In one sentence, why run a small model on a laptop?", LOCAL),
    ("api-1", "api", "In one sentence, what does continuous batching change on a GPU?", API),
    ("api-2", "api", "In one sentence, why does prefix caching cut prefill time?", API),
    ("any-1", "any", "In one sentence, what is time to first token?", LOCAL),
    ("any-2", "any", f"In one sentence, which status repeats in this log?\n{LOG}", API),
]


def routes(base_url: str = BASE_URL) -> list[Route]:
    return [
        Route(LOCAL, "local", LOCAL_MODEL, base_url, LOCAL_CONTEXT, 0.0, 0.0),
        Route(API, "api", API_MODEL, None, API_CONTEXT, API_IN, API_OUT),
    ]


def build(base_url: str = BASE_URL, *, health_path: str = HEALTH_PATH, query_fn=None):
    return gateway.Gateway(
        routes(base_url),
        prefer="local",
        query_fn=query_fn,
        timeout_s=TIMEOUT_S,
        health_path=health_path,
        extra_body=EXTRA_BODY,
    )


def run_plan(gw: gateway.Gateway) -> list[ChatResult]:
    return [gw.chat(ChatRequest(prompt, require, MAX_TOKENS)) for _, require, prompt, _ in PLAN]


def fits_locally(prompt: str) -> bool:
    return math.ceil(len(prompt) / 4) + MAX_TOKENS <= LOCAL_CONTEXT


def problems(results: list[ChatResult]) -> list[str]:
    found = []
    for (pid, require, _, expected), got in zip(PLAN, results, strict=True):
        if got.ok and got.route != expected:
            found.append(f"{pid}: answered by {got.route}, expected {expected}")
        if got.ok and not got.text.strip():
            found.append(f"{pid}: ok with an empty text")
        if not got.ok and not got.error:
            found.append(f"{pid}: failed without an error")
        if require == "local" and got.route != LOCAL:
            found.append(f"{pid}: require=local reached {got.route}")
    total = sum(r.cost_usd for r in results)
    if total > BUDGET_USD:
        found.append(f"total cost {total:.4f} USD above {BUDGET_USD}")
    return found


def aggregate(results: list[ChatResult], gw: gateway.Gateway) -> dict:
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "stage": "08-live-gateway",
        "local_model": LOCAL_MODEL,
        "api_model": API_MODEL,
        "local_context": LOCAL_CONTEXT,
        "max_tokens": MAX_TOKENS,
        "budget_usd": BUDGET_USD,
        "prompts": [
            {
                "id": pid,
                "require": require,
                "expected": expected,
                "route": got.route,
                "ok": got.ok,
                "latency_ms": round(got.latency_ms, 1),
                "cost_usd": round(got.cost_usd, 6),
                "tokens_out": got.tokens_out,
            }
            for (pid, require, _, expected), got in zip(PLAN, results, strict=True)
        ],
        "routes": {
            s.name: {
                "requests": s.requests,
                "failures": s.failures,
                "p50_latency_ms": round(s.p50_latency_ms, 1),
                "cost_usd": round(s.cost_usd, 6),
            }
            for s in gw.stats()
        },
        "total_cost_usd": round(sum(r.cost_usd for r in results), 6),
    }


def save(record: dict) -> Path:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "runs" / f"live-gateway-{record['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def model_pulled() -> bool:
    try:
        done = subprocess.run(
            ["ollama", "list"], check=False, capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    rows = [line.split() for line in done.stdout.splitlines()[1:]]
    return done.returncode == 0 and any(row and row[0] == LOCAL_MODEL for row in rows)


def logged_in() -> bool:
    try:
        from miubais.model import claude_available
    except ImportError:
        proc = subprocess.run(
            ["claude", "auth", "status"], check=False, capture_output=True, text=True
        )
        return proc.returncode == 0 and '"loggedIn": true' in proc.stdout
    return claude_available()


class FakeApi:
    def __init__(self, cost: float = 0.01) -> None:
        self.cost = cost
        self.prompts: list[str] = []

    def __call__(self, prompt=None, options=None, **_):
        self.prompts.append(prompt)
        done = ResultMessage(
            subtype="success",
            duration_ms=5,
            duration_api_ms=4,
            is_error=False,
            num_turns=1,
            session_id="s-1",
            total_cost_usd=self.cost,
            usage={"input_tokens": 30, "output_tokens": 12},
        )
        script = [AssistantMessage(content=[TextBlock(text="from the api")], model=API_MODEL), done]
        return scripted_query(script)(prompt=prompt, options=options)


def closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def result(route: str, *, ok: bool = True, text: str = "an answer", cost: float = 0.0, **kw):
    return ChatResult(route, text if ok else "", 10.0, cost, 3, ok=ok, **kw)


def expected_results() -> list[ChatResult]:
    return [result(expected, cost=0.01 if expected == API else 0.0) for *_, expected in PLAN]


def test_the_plan_has_two_prompts_per_requirement():
    assert Counter(require for _, require, _, _ in PLAN) == {"local": 2, "api": 2, "any": 2}
    assert len({pid for pid, *_ in PLAN}) == 6


def test_the_expected_routes_follow_the_routing_rule():
    for pid, require, prompt, expected in PLAN:
        if require == "any":
            assert expected == (LOCAL if fits_locally(prompt) else API), pid
        else:
            assert fits_locally(prompt), pid
    assert not fits_locally(PLAN[-1][2])


def test_the_plan_routes_as_expected_offline(fake_server):
    server = fake_server(model=LOCAL_MODEL, tokens_per_second=1000, first_token_ms=1)
    api = FakeApi()
    gw = build(server.base_url, health_path="/health", query_fn=api)
    results = run_plan(gw)
    assert [r.route for r in results] == [expected for *_, expected in PLAN]
    assert all(r.ok for r in results)
    assert problems(results) == []
    local_prompts = {prompt for _, require, prompt, _ in PLAN if require == "local"}
    assert len(api.prompts) == 3 and not local_prompts & set(api.prompts)
    by = {s.name: s for s in gw.stats()}
    assert (by[LOCAL].requests, by[API].requests) == (3, 3)


def test_local_only_prompts_fail_explicitly_when_the_local_route_is_down():
    api = FakeApi()
    results = run_plan(build(closed_port_url(), query_fn=api))
    for (pid, require, prompt, _), got in zip(PLAN, results, strict=True):
        if require == "local":
            assert (got.ok, got.route, got.cost_usd) == (False, LOCAL, 0.0), pid
            assert got.error and prompt not in api.prompts
        else:
            assert got.ok and got.route == API, pid
    assert problems(results) == [f"any-1: answered by {API}, expected {LOCAL}"]


def test_the_gateway_sends_the_extra_body_to_the_local_route():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == HEALTH_PATH else 404)
            self.end_headers()

        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = {
                "choices": [{"message": {"role": "assistant", "content": "a cache of keys"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            }
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        gw = build(f"http://127.0.0.1:{server.server_port}/v1", query_fn=FakeApi())
        got = gw.chat(ChatRequest(PLAN[0][2], "local", MAX_TOKENS))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert got.ok and got.route == LOCAL and got.text == "a cache of keys"
    assert seen[0]["reasoning_effort"] == "none"
    assert seen[0]["model"] == LOCAL_MODEL and seen[0]["max_tokens"] == MAX_TOKENS


def test_problems_name_what_fails():
    assert problems(expected_results()) == []
    wrong = expected_results()
    wrong[0] = result(API, cost=0.02)
    wrong[1] = result(LOCAL, ok=False)
    wrong[2] = result(API, text=" ")
    wrong[4] = result(API, ok=False, error="ollama: HTTP 500; claude: error_max_budget_usd")
    wrong[5] = result(API, cost=0.25)
    assert problems(wrong) == [
        f"local-1: answered by {API}, expected {LOCAL}",
        "local-1: require=local reached claude",
        "local-2: failed without an error",
        "api-1: ok with an empty text",
        "total cost 0.2800 USD above 0.2",
    ]


def test_the_aggregate_has_no_prompt_texts(fake_server):
    server = fake_server(model=LOCAL_MODEL, tokens_per_second=1000, first_token_ms=1)
    gw = build(server.base_url, health_path="/health", query_fn=FakeApi())
    record = aggregate(run_plan(gw), gw)
    dumped = json.dumps(record)
    assert all(prompt not in dumped for _, _, prompt, _ in PLAN)
    assert "from the api" not in dumped and "tok1" not in dumped
    assert [p["route"] for p in record["prompts"]] == [expected for *_, expected in PLAN]
    assert record["total_cost_usd"] == pytest.approx(0.03)
    assert record["routes"][API]["requests"] == 3


def test_the_committed_record_has_exactly_the_written_fields():
    committed = json.loads(RECORD.read_text())
    written = aggregate(expected_results(), build(query_fn=FakeApi()))
    assert committed.keys() == written.keys()
    assert committed["routes"].keys() == written["routes"].keys()
    assert [p.keys() for p in committed["prompts"]] == [p.keys() for p in written["prompts"]]
    assert [(p["id"], p["require"], p["expected"]) for p in committed["prompts"]] == [
        (pid, require, expected) for pid, require, _, expected in PLAN
    ]
    for p in committed["prompts"]:
        assert p["ok"] and p["route"] == p["expected"], p["id"]
        if p["require"] == "local":
            assert p["cost_usd"] == 0.0
    total = sum(p["cost_usd"] for p in committed["prompts"])
    assert committed["total_cost_usd"] == pytest.approx(total, abs=5e-6)
    assert total <= BUDGET_USD
    assert committed["budget_usd"] == BUDGET_USD and committed["max_tokens"] == MAX_TOKENS


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
def test_live_gateway_routes_six_prompts():
    if not model_pulled():
        pytest.skip(SKIP_MESSAGE)
    if not logged_in():
        pytest.skip("needs claude-auth")
    gw = build()
    results = run_plan(gw)
    record = aggregate(results, gw)
    print(f"\nlive gateway: {json.dumps(record, indent=2)}")
    print(gw.to_markdown())
    for (pid, *_), got in zip(PLAN, results, strict=True):
        print(f"{pid}: {got.route} ok={got.ok} error={got.error}")
    print(f"saved {save(record)}")
    assert problems(results) == [], problems(results)
