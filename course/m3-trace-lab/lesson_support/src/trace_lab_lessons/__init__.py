import base64
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock, UserMessage
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as gen_ai

TRACES_PATH = "/api/public/otel/v1/traces"
OBSERVATIONS_PATH = "/api/public/v2/observations"


@dataclass
class SpanNode:
    name: str
    parent: str | None
    start_ms: int
    end_ms: int
    error: str | None = None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def span_tree(timed: Iterable[Any], agent_name: str = "ticket-runner") -> list[SpanNode]:
    root = SpanNode(f"invoke_agent {agent_name}", None, 0, 0)
    nodes = [root]
    open_tools: dict[str, SpanNode] = {}
    seen: set[str] = set()
    previous_ms = 0
    for item in timed:
        message, at = item.message, item.at_ms
        if isinstance(message, dict):
            continue
        root.end_ms = max(root.end_ms, at)
        if isinstance(message, AssistantMessage):
            if message.message_id not in seen:
                seen.add(message.message_id)
                nodes.append(SpanNode(f"chat {message.model}", root.name, previous_ms, at))
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    tool = SpanNode(f"execute_tool {block.name}", root.name, at, at)
                    open_tools[block.id] = tool
                    nodes.append(tool)
        elif isinstance(message, UserMessage) and not isinstance(message.content, str):
            for block in message.content:
                tool = open_tools.pop(getattr(block, "tool_use_id", None), None)
                if tool is not None:
                    tool.end_ms = at
                    tool.error = "tool_error" if block.is_error else None
        elif isinstance(message, ResultMessage) and message.subtype.startswith("error_"):
            root.error = message.subtype
        previous_ms = at
    for tool in open_tools.values():
        tool.end_ms, tool.error = root.end_ms, "no_result"
    return nodes


def render_tree(nodes: list[SpanNode]) -> str:
    lines = []
    for node in nodes:
        indent = "" if node.parent is None else "  "
        label = f"{indent}{node.name}"
        error = f"  error.type={node.error}" if node.error else ""
        lines.append(f"{label:<34} {node.start_ms:>6} ms {node.duration_ms:>6} ms{error}")
    return "\n".join(lines)


def anthropic_input_tokens(usage: Mapping[str, int]) -> int:
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
    )


def inference_attributes(
    model: str,
    usage: Mapping[str, int],
    *,
    response_id: str | None = None,
    finish_reason: str | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        gen_ai.GEN_AI_OPERATION_NAME: gen_ai.GenAiOperationNameValues.CHAT.value,
        gen_ai.GEN_AI_PROVIDER_NAME: gen_ai.GenAiProviderNameValues.ANTHROPIC.value,
        gen_ai.GEN_AI_REQUEST_MODEL: model,
        gen_ai.GEN_AI_RESPONSE_MODEL: model,
        gen_ai.GEN_AI_USAGE_INPUT_TOKENS: anthropic_input_tokens(usage),
        gen_ai.GEN_AI_USAGE_OUTPUT_TOKENS: usage.get("output_tokens", 0),
        gen_ai.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS: usage.get("cache_read_input_tokens", 0),
        gen_ai.GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS: usage.get(
            "cache_creation_input_tokens", 0
        ),
    }
    if response_id is not None:
        attributes[gen_ai.GEN_AI_RESPONSE_ID] = response_id
    if finish_reason is not None:
        attributes[gen_ai.GEN_AI_RESPONSE_FINISH_REASONS] = [finish_reason]
    return attributes


def langfuse_headers(public_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return {"Authorization": f"Basic {token}", "x-langfuse-ingestion-version": "4"}


def otlp_traces_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{TRACES_PATH}"


def observations_url(base_url: str, trace_id: str, limit: int = 100) -> str:
    query = urlencode({"traceId": trace_id, "limit": limit})
    return f"{base_url.rstrip('/')}{OBSERVATIONS_PATH}?{query}"


@dataclass
class RunCost:
    ticket_id: str
    usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    reported_usd: float | None

    @property
    def cache_hit_ratio(self) -> float:
        prompt = self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        return self.cache_read_tokens / prompt if prompt else 0.0


def load_prices(path: str | Path = "fixtures/harness-runs/prices.json") -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def message_cost(model: str, usage: Mapping[str, int], prices: Mapping[str, Any]) -> float:
    price = prices[model]
    return (
        usage.get("input_tokens", 0) * price["input"]
        + usage.get("output_tokens", 0) * price["output"]
        + usage.get("cache_read_input_tokens", 0) * price["cache_read"]
        + usage.get("cache_creation_input_tokens", 0) * price["cache_write_5m"]
    ) / 1e6


def run_cost(timed: Iterable[Any], prices: Mapping[str, Any]) -> RunCost:
    cost = RunCost("", 0.0, 0, 0, 0, 0, None)
    counted: set[str] = set()
    for item in timed:
        message = item.message
        if isinstance(message, dict):
            cost.ticket_id = message.get("ticket_id", cost.ticket_id)
        elif isinstance(message, ResultMessage):
            cost.reported_usd = message.total_cost_usd
        elif isinstance(message, AssistantMessage) and message.usage:
            # parallel tool calls repeat one message id with identical usage
            if message.message_id in counted:
                continue
            counted.add(message.message_id)
            usage = message.usage
            cost.usd += message_cost(message.model, usage, prices)
            cost.input_tokens += usage.get("input_tokens", 0)
            cost.output_tokens += usage.get("output_tokens", 0)
            cost.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
            cost.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)
    return cost


def per_ticket(runs: Iterable[RunCost]) -> dict[str, RunCost]:
    totals: dict[str, RunCost] = {}
    for run in runs:
        acc = totals.setdefault(run.ticket_id, RunCost(run.ticket_id, 0.0, 0, 0, 0, 0, None))
        acc.usd += run.usd
        acc.input_tokens += run.input_tokens
        acc.output_tokens += run.output_tokens
        acc.cache_read_tokens += run.cache_read_tokens
        acc.cache_write_tokens += run.cache_write_tokens
    return totals


def top_share(values: Iterable[float], fraction: float = 0.25) -> float:
    ordered = sorted(values, reverse=True)
    total = sum(ordered)
    if not total:
        return 0.0
    count = max(1, round(len(ordered) * fraction))
    return sum(ordered[:count]) / total


def cost_summary(runs: list[RunCost]) -> dict[str, float]:
    tickets = per_ticket(runs)
    deltas = [abs(r.usd - r.reported_usd) for r in runs if r.reported_usd is not None]
    return {
        "runs": len(runs),
        "tickets": len(tickets),
        "total_usd": sum(r.usd for r in runs),
        "mean_ticket_cache_hit": sum(t.cache_hit_ratio for t in tickets.values()) / len(tickets),
        "top_quartile_run_share": top_share(r.usd for r in runs),
        "runs_with_result": len(deltas),
        "max_reconcile_delta": max(deltas, default=0.0),
    }


@dataclass(frozen=True)
class Route:
    name: str
    model: str
    max_budget_usd: float
    max_turns: int


@dataclass(frozen=True)
class Outcome:
    stopped_by: str
    cost_usd: float
    turns: int


@dataclass
class RouteStats:
    attempts: int = 0
    successes: int = 0
    cost_usd: float = 0.0
    turns: int = 0


class LessonRouter:
    def __init__(
        self,
        routes: list[Route],
        fallback_on: frozenset[str] = frozenset({"budget", "max_turns", "error"}),
    ) -> None:
        if fallback_on & {"success", "policy"}:
            raise ValueError("success and policy stops never fall back")
        self.routes = routes
        self.fallback_on = fallback_on
        self.stats = {route.name: RouteStats() for route in routes}

    def run(self, ticket_id: str, run_fn: Any) -> tuple[str, list[tuple[str, Outcome]]]:
        attempts: list[tuple[str, Outcome]] = []
        for route in self.routes:
            outcome = run_fn(
                ticket_id,
                model=route.model,
                max_turns=route.max_turns,
                max_budget_usd=route.max_budget_usd,
            )
            stats = self.stats[route.name]
            stats.attempts += 1
            stats.successes += outcome.stopped_by == "success"
            stats.cost_usd += outcome.cost_usd
            stats.turns += outcome.turns
            attempts.append((route.name, outcome))
            if outcome.stopped_by not in self.fallback_on:
                break
        return route.name, attempts

    def table(self) -> str:
        lines = [f"{'route':<8} {'model':<18} {'tries':>5} {'ok':>3} {'usd':>8} {'turns':>5}"]
        for route in self.routes:
            s = self.stats[route.name]
            lines.append(
                f"{route.name:<8} {route.model:<18} {s.attempts:>5} {s.successes:>3} "
                f"{s.cost_usd:>8.4f} {s.turns:>5}"
            )
        return "\n".join(lines)


def percentile(values: list[float], q: float) -> float:
    # nearest rank, so every reported value is one that was observed
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no values")
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def tool_durations(timed: Iterable[Any]) -> list[SpanNode]:
    return [n for n in span_tree(timed) if n.name.startswith("execute_tool ")]


def tool_latency_table(tool_spans: Iterable[SpanNode]) -> str:
    by_tool: dict[str, list[int]] = {}
    unfinished = 0
    for node in tool_spans:
        if node.error == "no_result":
            unfinished += 1
            continue
        by_tool.setdefault(node.name.removeprefix("execute_tool "), []).append(node.duration_ms)
    lines = [f"{'tool':<6} {'n':>4} {'p50':>6} {'p90':>6} {'p99':>6} {'max':>6}"]
    for name in sorted(by_tool):
        values = by_tool[name]
        cells = [percentile(values, q) for q in (50, 90, 99)] + [max(values)]
        lines.append(f"{name:<6} {len(values):>4} " + " ".join(f"{c:>6}" for c in cells))
    lines.append(f"unfinished (no_result, left out): {unfinished}")
    return "\n".join(lines)


def parallel_turns(timed: Iterable[Any]) -> tuple[int, int]:
    tools_per_turn: dict[str, int] = {}
    for item in timed:
        message = item.message
        if isinstance(message, AssistantMessage):
            uses = sum(isinstance(b, ToolUseBlock) for b in message.content)
            if uses:
                tools_per_turn[message.message_id] = (
                    tools_per_turn.get(message.message_id, 0) + uses
                )
    return sum(n > 1 for n in tools_per_turn.values()), len(tools_per_turn)
