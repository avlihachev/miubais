import socket

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from harnesskit.testing import scripted_query
from serving_lab import gateway
from serving_lab.types import ChatRequest, Route, RouteStats

LOCAL_MODEL = "fake-7b"
API_MODEL = "claude-opus-5-5"
API_COST = 0.0123
LOCAL_IN, LOCAL_OUT = 0.10, 0.40
API_IN, API_OUT = 4.0, 20.0


def result(cost: float | None = API_COST, subtype: str = "success", out: int = 7):
    return ResultMessage(
        subtype=subtype,
        duration_ms=5,
        duration_api_ms=4,
        is_error=subtype != "success",
        num_turns=1,
        session_id="s-1",
        total_cost_usd=cost,
        usage={"input_tokens": 20, "output_tokens": out},
    )


def reply(text: str = "from the api", **kw) -> list:
    return [AssistantMessage(content=[TextBlock(text=text)], model=API_MODEL), result(**kw)]


class Api:
    def __init__(self, *scripts: list) -> None:
        self.scripts = list(scripts)
        self.calls: list[tuple] = []

    def __call__(self, prompt=None, options=None, **_):
        self.calls.append((prompt, options))
        script = self.scripts.pop(0) if self.scripts else reply()
        return scripted_query(script)(prompt=prompt, options=options)


def local_route(base_url: str, *, max_tokens: int = 4096, model: str = LOCAL_MODEL) -> Route:
    return Route("local", "local", model, base_url, max_tokens, LOCAL_IN, LOCAL_OUT)


def api_route() -> Route:
    return Route("claude", "api", API_MODEL, None, 200_000, API_IN, API_OUT)


def make(base_url: str, api: Api, **kw) -> gateway.Gateway:
    local_kw = {k: kw.pop(k) for k in ("max_tokens", "model") if k in kw}
    routes = [local_route(base_url, **local_kw), api_route()]
    return gateway.Gateway(routes, query_fn=api, **kw)


def closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def stats(gw: gateway.Gateway) -> dict[str, RouteStats]:
    return {s.name: s for s in gw.stats()}


def ask(gw: gateway.Gateway, require: str = "any", prompt: str = "say hi please", n: int = 8):
    return gw.chat(ChatRequest(prompt, require=require, max_tokens=n))


def test_prefers_the_local_route(fake_server):
    server = fake_server(tokens_per_second=500, first_token_ms=5)
    api = Api()
    got = ask(make(server.base_url, api))
    assert got.ok and got.error is None
    assert got.route == "local"
    assert got.text == "tok1 tok2 tok3 tok4 tok5 tok6 tok7 tok8"
    assert got.tokens_out == 8
    assert got.cost_usd == pytest.approx((3 * LOCAL_IN + 8 * LOCAL_OUT) / 1e6)
    assert got.latency_ms > 0
    assert api.calls == []


def test_require_api_goes_to_the_agent_sdk_with_a_capped_call(fake_server):
    server = fake_server()
    api = Api(reply("hello from claude"))
    got = ask(make(server.base_url, api), require="api")
    assert got.ok and got.route == "claude"
    assert got.text == "hello from claude"
    assert got.cost_usd == pytest.approx(API_COST)
    assert got.tokens_out == 7
    [(prompt, options)] = api.calls
    assert prompt == "say hi please"
    assert options.model == API_MODEL
    assert options.tools == []
    assert options.max_turns == 1
    assert options.max_budget_usd == 0.05
    assert server.counters["e2e_count"] == 0


def test_api_cost_falls_back_to_route_prices_without_a_reported_cost(fake_server):
    api = Api(reply(cost=None))
    got = ask(make(fake_server().base_url, api), require="api")
    assert got.cost_usd == pytest.approx((20 * API_IN + 7 * API_OUT) / 1e6)


def test_local_5xx_falls_back_to_the_api(fake_server):
    server = fake_server(fail_status=503)
    api = Api()
    gw = make(server.base_url, api)
    got = ask(gw)
    assert got.ok and got.route == "claude"
    assert len(api.calls) == 1
    by = stats(gw)
    assert (by["local"].requests, by["local"].failures) == (1, 1)
    assert (by["claude"].requests, by["claude"].failures) == (1, 0)


def test_local_timeout_falls_back_to_the_api(fake_server):
    server = fake_server(queue_delay_ms=1500)
    api = Api()
    gw = make(server.base_url, api, timeout_s=0.3)
    got = ask(gw)
    assert got.ok and got.route == "claude"
    assert got.latency_ms >= 300
    assert stats(gw)["local"].failures == 1


def test_local_4xx_is_a_failure_without_fallback(fake_server):
    server = fake_server()
    api = Api()
    got = ask(make(server.base_url, api, model="not-served"))
    assert not got.ok and got.route == "local"
    assert "HTTP 404" in got.error
    assert api.calls == []


def test_unhealthy_local_routes_to_the_api_without_trying_local(fake_server):
    server = fake_server(healthy=False)
    api = Api()
    gw = make(server.base_url, api)
    got = ask(gw)
    assert got.ok and got.route == "claude"
    assert server.counters["e2e_count"] == 0
    assert stats(gw)["local"].requests == 0


def test_health_slower_than_one_second_counts_as_unhealthy(fake_server):
    server = fake_server(health_delay_ms=1500)
    api = Api()
    got = ask(make(server.base_url, api))
    assert got.route == "claude"
    assert server.counters["e2e_count"] == 0


def test_health_is_probed_on_every_request(fake_server):
    server = fake_server(tokens_per_second=500, first_token_ms=5)
    gw = make(server.base_url, Api())
    assert ask(gw).route == "local"
    server.healthy = False
    assert ask(gw).route == "claude"
    server.healthy = True
    assert ask(gw).route == "local"


def test_down_local_routes_to_the_api():
    api = Api()
    got = ask(make(closed_port_url(), api))
    assert got.ok and got.route == "claude"


def test_prompt_that_does_not_fit_the_local_route_goes_to_the_api(fake_server):
    server = fake_server(tokens_per_second=500, first_token_ms=5)
    gw = make(server.base_url, Api(), max_tokens=64)
    assert ask(gw, prompt="x" * 40, n=54).route == "local"
    assert ask(gw, prompt="x" * 44, n=54).route == "claude"
    assert server.counters["e2e_count"] == 1


@pytest.mark.parametrize(
    "knobs", [{"healthy": False}, {"fail_status": 500}, {"queue_delay_ms": 1500}]
)
def test_require_local_never_reaches_the_api(fake_server, knobs):
    server = fake_server(**knobs)
    api = Api()
    gw = make(server.base_url, api, timeout_s=0.3)
    got = ask(gw, require="local")
    assert not got.ok
    assert got.route == "local"
    assert got.error
    assert got.text == "" and got.cost_usd == 0.0
    assert api.calls == []
    assert stats(gw)["claude"].requests == 0
    assert (stats(gw)["local"].requests, stats(gw)["local"].failures) == (1, 1)


def test_require_local_with_the_local_server_down_fails():
    api = Api()
    got = ask(make(closed_port_url(), api), require="local")
    assert not got.ok and got.route == "local"
    assert api.calls == []


def test_require_local_with_a_prompt_too_long_fails(fake_server):
    api = Api()
    got = ask(make(fake_server().base_url, api, max_tokens=64), require="local", prompt="x" * 400)
    assert not got.ok and api.calls == []


def test_api_error_result_is_a_failure_and_its_cost_counts(fake_server):
    api = Api(reply(cost=0.05, subtype="error_max_budget_usd"))
    gw = make(fake_server().base_url, api)
    got = ask(gw, require="api")
    assert not got.ok and got.route == "claude"
    assert "error_max_budget_usd" in got.error
    assert got.cost_usd == pytest.approx(0.05)
    by = stats(gw)["claude"]
    assert (by.requests, by.failures) == (1, 1)
    assert by.cost_usd == pytest.approx(0.05)


def test_both_routes_failing_is_an_explicit_failure(fake_server):
    server = fake_server(fail_status=502)
    api = Api(reply(cost=0.0, subtype="error_during_execution"))
    got = ask(make(server.base_url, api))
    assert not got.ok
    assert "local: HTTP 502" in got.error and "claude:" in got.error


def test_prefer_api_falls_back_to_local_on_api_failure(fake_server):
    server = fake_server(tokens_per_second=500, first_token_ms=5)
    api = Api(reply(), reply(cost=0.0, subtype="error_during_execution"))
    gw = make(server.base_url, api, prefer="api")
    assert ask(gw).route == "claude"
    assert ask(gw).route == "local"
    assert ask(gw, require="local").route == "local"
    assert len(api.calls) == 2


def test_stats_and_report_account_cost_by_route(fake_server):
    server = fake_server(tokens_per_second=500, first_token_ms=5)
    api = Api(reply(cost=0.01), reply(cost=0.02))
    gw = make(server.base_url, api)
    ask(gw)
    ask(gw, n=4)
    ask(gw, require="api")
    ask(gw, require="api")
    by = stats(gw)
    assert [s.name for s in gw.stats()] == ["local", "claude"]
    local_cost = (6 * LOCAL_IN + 12 * LOCAL_OUT) / 1e6
    assert (by["local"].requests, by["local"].failures) == (2, 0)
    assert (by["claude"].requests, by["claude"].failures) == (2, 0)
    assert by["local"].cost_usd == pytest.approx(local_cost)
    assert by["claude"].cost_usd == pytest.approx(0.03)
    assert by["local"].p50_latency_ms > 0 and by["claude"].p50_latency_ms > 0
    report = gw.to_markdown()
    lines = report.strip().splitlines()
    assert lines[0] == (
        "| route | kind | model | requests | failures | p50 latency (ms) | cost (USD) |"
    )
    assert lines[2].startswith(f"| local | local | {LOCAL_MODEL} | 2 | 0 | ")
    assert lines[2].endswith(f"| {local_cost:.6f} |")
    assert lines[3].startswith(f"| claude | api | {API_MODEL} | 2 | 0 | ")
    assert lines[3].endswith("| 0.030000 |")
    assert lines[4] == f"| total | | | 4 | 0 | | {local_cost + 0.03:.6f} |"


def test_routes_without_traffic_report_zeros(fake_server):
    gw = make(fake_server().base_url, Api())
    assert gw.stats() == [RouteStats("local", 0, 0, 0.0, 0.0), RouteStats("claude", 0, 0, 0.0, 0.0)]
