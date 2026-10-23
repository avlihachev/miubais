from dataclasses import dataclass, field

from harnesskit.report import RunReport
from opentelemetry.sdk.trace import ReadableSpan

TRACE_LAB_TICKET_ID = "trace_lab.ticket_id"
TRACE_LAB_COST_USD = "trace_lab.cost_usd"
TRACE_LAB_ROUTE = "trace_lab.route"


@dataclass
class RunTrace:
    trace_id: str
    ticket_id: str
    spans: list[ReadableSpan]


@dataclass(frozen=True)
class TaskCost:
    ticket_id: str
    usd: float
    calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cache_hit_ratio: float


@dataclass(frozen=True)
class Reconciliation:
    from_spans: float
    reported: float | None
    delta: float | None


@dataclass(frozen=True)
class ExportSummary:
    traces: int
    spans: int
    failed: int
    failed_spans: int


@dataclass(frozen=True)
class Route:
    name: str
    model: str
    max_budget_usd: float
    max_turns: int


@dataclass(frozen=True)
class Attempt:
    route: str
    stopped_by: str
    cost_usd: float


@dataclass
class Routed:
    report: RunReport
    route: str
    attempts: list[Attempt] = field(default_factory=list)


@dataclass
class RouteStats:
    name: str
    attempts: int = 0
    successes: int = 0
    cost_usd: float = 0.0
    turns: int = 0
