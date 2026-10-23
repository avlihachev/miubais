import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter
from contextlib import aclosing
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from conftest import LAB, REPO_ROOT
from harnesskit.policy import Policy
from harnesskit.runner import default_query
from harnesskit.sessions import SessionStore
from harnesskit.testing import Timed
from trace_lab import budget, export, spans
from trace_lab.cost import Prices

LANGFUSE = "http://localhost:3000"
PUBLIC_KEY = "pk-lf-miubais"
SECRET_KEY = "sk-lf-miubais"
COMPOSE = LAB / "docker-compose.yml"
NEEDS_LANGFUSE = "needs Langfuse: docker compose -f course/m3-trace-lab/docker-compose.yml up -d"
TINYSHOP = REPO_ROOT / "fixtures" / "tinyshop"
TICKET_ID = "001-discount-rounding"
MODEL = "claude-opus-5-5"
LIMIT_USD = 0.75
MAX_TURNS = 12
ROOT = "invoke_agent ticket-runner"
POLL_SECONDS = 60
MAX_OBSERVATIONS = 100
IMAGES = {
    "langfuse-web": "docker.langfuse.com/langfuse/langfuse:4",
    "langfuse-worker": "docker.langfuse.com/langfuse/langfuse-worker:4",
    "clickhouse": "docker.io/clickhouse/clickhouse-server:25.12",
    "postgres": "docker.io/postgres:17",
    "redis": "docker.io/redis:7",
    "minio": "cgr.dev/chainguard/minio",
}


def logged_in() -> bool:
    try:
        from miubais.model import claude_available
    except ImportError:
        proc = subprocess.run(
            ["claude", "auth", "status"], check=False, capture_output=True, text=True
        )
        return proc.returncode == 0 and '"loggedIn": true' in proc.stdout
    return claude_available()


def compose_services(stdout: str) -> list[dict]:
    text = stdout.strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def langfuse_ready() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "ps", "--format", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    return web_ready(compose_services(proc.stdout))


def web_ready(services: list[dict]) -> bool:
    return any(
        s.get("Service") == "langfuse-web"
        and s.get("State") == "running"
        and s.get("Health") == "healthy"
        for s in services
    )


class Clock:
    def __init__(self, query_fn=default_query):
        self.query_fn = query_fn
        self.started: float | None = None
        self.started_ns: int | None = None
        self.timed: list[Timed] = []

    def __call__(self, prompt, options):
        return self._stream(prompt, options)

    async def _stream(self, prompt, options):
        if self.started is None:
            self.started = time.monotonic()
            self.started_ns = time.time_ns()
        async with aclosing(self.query_fn(prompt, options)) as messages:
            async for message in messages:
                at_ms = round((time.monotonic() - self.started) * 1000)
                self.timed.append(Timed(at_ms, message))
                yield message


def timed_run(clock: Clock, report) -> list[Timed]:
    meta = {"type": "meta", "ticket_id": report.ticket_id, "session_id": report.session_id}
    return [Timed(0, meta), *clock.timed]


def observation_problems(observations: list[dict]) -> list[str]:
    roots = [o for o in observations if o.get("parentObservationId") is None]
    if len(roots) != 1:
        return [f"expected one root observation, got {len(roots)}"]
    root, found = roots[0], []
    if root.get("name") != ROOT:
        found.append(f"root is {root.get('name')!r}, expected {ROOT!r}")
    children = [o for o in observations if o is not root]
    strays = [o["name"] for o in children if o.get("parentObservationId") != root["id"]]
    if strays:
        found.append(f"not children of the root: {strays}")
    if not any(o.get("type") == "GENERATION" and o["name"].startswith("chat ") for o in children):
        found.append("no chat generation under the root")
    if not any(o.get("type") == "TOOL" for o in children):
        found.append("no tool observation under the root")
    return found


def record_problems(record: dict) -> list[str]:
    found = []
    cost = record.get("cost_usd")
    if isinstance(cost, bool) or not isinstance(cost, int | float) or cost <= 0:
        found.append(f"cost_usd must be a positive number, got {cost!r}")
    if record.get("stopped_by") != "success":
        found.append(f"stopped_by {record.get('stopped_by')!r}, expected success")
    if not re.fullmatch(r"[0-9a-f]{32}", str(record.get("trace_id"))):
        found.append(f"trace_id {record.get('trace_id')!r} is not a 32-digit hex OTel trace id")
    observations = record.get("observations", {})
    if observations.get("AGENT") != 1:
        found.append(f"expected one AGENT observation, got {observations.get('AGENT')}")
    for kind in ("GENERATION", "TOOL"):
        if not observations.get(kind):
            found.append(f"no {kind} observations")
    return found


def save(record: dict, workspace: Path) -> Path:
    path = workspace / "runs" / f"live-{datetime.now(UTC).date().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def langfuse_get(path: str, **params) -> dict:
    token = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
    url = f"{LANGFUSE}{path}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def read_back(trace_id: str, expected: int) -> list[dict]:
    assert expected <= MAX_OBSERVATIONS, f"{expected} spans do not fit one page of observations"
    deadline = time.monotonic() + POLL_SECONDS
    found: list[dict] = []
    while time.monotonic() < deadline:
        found = langfuse_get(
            "/api/public/v2/observations", traceId=trace_id, limit=MAX_OBSERVATIONS
        )["data"]
        if len(found) >= expected:
            break
        time.sleep(2)
    return found


@pytest.fixture
def workspace() -> Path:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    return Path(root)


def git(repo: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


@pytest.fixture
def shop(tmp_path) -> Path:
    repo = tmp_path / "tinyshop"
    shutil.copytree(TINYSHOP, repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "-c", "user.name=lab", "-c", "user.email=lab@example.com", "commit", "-qm", "base")
    return repo


def endpoint_of(exporter) -> str:
    return exporter._endpoint


def test_the_exporter_targets_the_local_langfuse():
    exporter = export.langfuse_exporter(LANGFUSE, PUBLIC_KEY, SECRET_KEY)
    assert endpoint_of(exporter) == f"{LANGFUSE}/api/public/otel/v1/traces"
    token = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
    assert export.langfuse_headers(PUBLIC_KEY, SECRET_KEY) == {
        "Authorization": f"Basic {token}",
        "x-langfuse-ingestion-version": "4",
    }


def test_the_compose_file_pins_the_stack():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    assert {name: s["image"] for name, s in services.items()} == IMAGES
    published = [port for s in services.values() for port in s.get("ports", [])]
    assert published and all(str(port).startswith("127.0.0.1:") for port in published)
    web = services["langfuse-web"]
    assert web["healthcheck"]["test"]
    assert web["environment"]["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"] == PUBLIC_KEY
    assert web["environment"]["LANGFUSE_INIT_PROJECT_SECRET_KEY"] == SECRET_KEY


def test_compose_ps_output_is_read_in_both_formats():
    web = {"Service": "langfuse-web", "State": "running", "Health": "healthy"}
    db = {"Service": "postgres", "State": "running", "Health": "healthy"}
    lines = "\n".join(json.dumps(s) for s in (db, web))
    assert compose_services(lines) == compose_services(json.dumps([db, web])) == [db, web]
    assert web_ready([db, web])
    for health in ("", "starting", "unhealthy"):
        assert not web_ready([db, {**web, "Health": health}]), health
    assert not web_ready([db, {**web, "State": "exited"}])


def usage(n):
    return {
        "input_tokens": 1_000,
        "output_tokens": 200 * n,
        "cache_read_input_tokens": 30_000,
        "cache_creation_input_tokens": 2_000,
    }


def scripted_stream():
    def turn(n, block):
        return AssistantMessage(
            content=[block], model=MODEL, usage=usage(n), message_id=f"m{n}", session_id="s-1"
        )

    return [
        turn(1, ToolUseBlock(id="t1", name="Read", input={"file_path": "src/a.py"})),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="x", is_error=False)]),
        turn(2, ToolUseBlock(id="t2", name="Edit", input={"file_path": "src/a.py"})),
        UserMessage(content=[ToolResultBlock(tool_use_id="t2", content="ok", is_error=False)]),
        turn(3, TextBlock(text="done")),
        ResultMessage(
            subtype="success",
            duration_ms=5,
            duration_api_ms=4,
            is_error=False,
            num_turns=3,
            session_id="s-1",
            total_cost_usd=0.2,
        ),
    ]


@pytest.mark.parametrize("limit", [0.05, 1.0], ids=["guard-trips", "under-budget"])
def test_the_clock_keeps_the_guard_in_charge(scripted, shop, tmp_path, prices_path, limit):
    clock = Clock(scripted(scripted_stream()))
    with SessionStore(tmp_path / "s.db") as store:
        report = budget.run_with_budget(
            shop / "tickets" / f"{TICKET_ID}.md",
            shop,
            limit_usd=limit,
            prices=Prices.load(prices_path),
            policy=Policy(writable=[shop / "src"]),
            store=store,
            query_fn=clock,
        )
    assert report.stopped_by == ("budget" if limit < 1.0 else "success")
    assert [item.message for item in clock.timed] == report.messages
    stamps = [item.at_ms for item in clock.timed]
    assert stamps == sorted(stamps)
    provider, exporter = spans.provider_for_tests()
    run = spans.record_run(
        timed_run(clock, report),
        ticket_id=TICKET_ID,
        tracer_provider=provider,
        epoch_ns=clock.started_ns,
    )
    names = Counter(span.name.split(" ")[0] for span in exporter.get_finished_spans())
    assert names["invoke_agent"] == 1 and names["chat"] >= 1 and names["execute_tool"] >= 1
    assert len(run.trace_id) == 32


def observation(id, name, kind, parent):
    return {"id": id, "name": name, "type": kind, "parentObservationId": parent}


def test_the_observation_tree_check():
    good = [
        observation("a", ROOT, "AGENT", None),
        observation("b", f"chat {MODEL}", "GENERATION", "a"),
        observation("c", "Read", "TOOL", "a"),
    ]
    assert observation_problems(good) == []
    assert observation_problems([*good, observation("d", ROOT, "AGENT", None)]) == [
        "expected one root observation, got 2"
    ]
    assert observation_problems(good[:2]) == ["no tool observation under the root"]
    nested = [*good[:2], observation("c", "Read", "TOOL", "b")]
    assert observation_problems(nested) == ["not children of the root: ['Read']"]


def test_the_record_check():
    record = {
        "cost_usd": 0.31,
        "stopped_by": "success",
        "trace_id": "0" * 31 + "1",
        "observations": {"AGENT": 1, "GENERATION": 5, "TOOL": 6},
    }
    assert record_problems(record) == []
    for field, value in [("cost_usd", 0.0), ("stopped_by", "budget"), ("trace_id", "abc")]:
        assert record_problems({**record, field: value}), field
    assert record_problems({**record, "observations": {"AGENT": 1, "GENERATION": 5}}) == [
        "no TOOL observations"
    ]


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not logged_in(), reason="needs claude-auth")
def test_live_traced_ticket(shop, tmp_path, workspace, prices_path):
    if not langfuse_ready():
        pytest.skip(NEEDS_LANGFUSE)
    clock = Clock()
    provider = export.provider(export.langfuse_exporter(LANGFUSE, PUBLIC_KEY, SECRET_KEY))
    with SessionStore(tmp_path / "s.db") as store:
        report = budget.run_with_budget(
            shop / "tickets" / f"{TICKET_ID}.md",
            shop,
            limit_usd=LIMIT_USD,
            prices=Prices.load(prices_path),
            policy=Policy(writable=[shop / "src"]),
            store=store,
            model=MODEL,
            max_turns=MAX_TURNS,
            query_fn=clock,
        )
    run = spans.record_run(
        timed_run(clock, report),
        ticket_id=TICKET_ID,
        tracer_provider=provider,
        epoch_ns=clock.started_ns,
    )
    provider.force_flush()
    provider.shutdown()
    observations = read_back(run.trace_id, len(run.spans))
    span_kinds = Counter(span.name.split(" ")[0] for span in run.spans)
    record = {
        "date": datetime.now(UTC).date().isoformat(),
        "stage": "08-live-traced-ticket",
        "ticket": TICKET_ID,
        "model": MODEL,
        "limit_usd": LIMIT_USD,
        "stopped_by": report.stopped_by,
        "turns": report.turns,
        "cost_usd": report.cost_usd,
        "duration_ms": clock.timed[-1].at_ms if clock.timed else 0,
        "files_changed": report.files_changed,
        "trace_id": run.trace_id,
        "spans": dict(span_kinds),
        "observations": dict(Counter(o.get("type") for o in observations)),
    }
    print(f"\nlive traced ticket: {json.dumps(record)}")
    if report.stopped_by == "success":
        print(f"saved {save(record, workspace)}")
    assert len(observations) == len(run.spans), (len(observations), len(run.spans))
    assert observation_problems(observations) == []
    assert record_problems(record) == []
