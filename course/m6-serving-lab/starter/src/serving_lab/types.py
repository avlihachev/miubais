from dataclasses import dataclass, field
from typing import Literal

RouteKind = Literal["local", "api"]
Requirement = Literal["any", "local", "api"]


@dataclass(frozen=True)
class RequestResult:
    prompt_id: int
    ttft_ms: float | None
    tps: float | None
    latency_ms: float
    output_tokens: int
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class Summary:
    n: int
    failed: int
    p50_ttft_ms: float
    p90_ttft_ms: float
    p99_ttft_ms: float
    p50_tps: float
    throughput_tps: float
    wall_s: float


@dataclass(frozen=True)
class RunResult:
    requests: list[RequestResult]
    summary: Summary


@dataclass(frozen=True)
class Route:
    name: str
    kind: RouteKind
    model: str
    base_url: str | None
    max_tokens: int
    price_per_mtok_in: float
    price_per_mtok_out: float


@dataclass(frozen=True)
class RouteStats:
    name: str
    requests: int
    failures: int
    p50_latency_ms: float
    cost_usd: float


@dataclass(frozen=True)
class ChatRequest:
    prompt: str
    require: Requirement = "any"
    max_tokens: int = 256


@dataclass(frozen=True)
class ChatResult:
    route: str
    text: str
    latency_ms: float
    cost_usd: float
    tokens_out: int
    ok: bool = True
    error: str | None = None


@dataclass(frozen=True)
class ScalePolicy:
    min_replicas: int
    max_replicas: int
    target_waiting: float
    activation: float
    stabilisation_s: int
    cooldown_s: int


@dataclass(frozen=True)
class Sample:
    t_s: int
    waiting: float
    running: float


@dataclass(frozen=True)
class ScaleDecision:
    t_s: int
    replicas: int
    reason: str


@dataclass(frozen=True)
class BenchmarkInput:
    gpu: str
    gpu_usd_per_hour: float
    model: str
    quantisation: str
    tp_size: int
    max_model_len: int
    summary: Summary
    run_s: float
    api_usd_per_mtok_out: float | None = None


@dataclass(frozen=True)
class BenchmarkReport:
    input: BenchmarkInput
    output_tokens: int
    output_tokens_per_hour: float
    usd_per_mtok_out: float
    usd_per_request: float
    api_usd_per_mtok_out: float | None = None


@dataclass(frozen=True)
class Validation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass(frozen=True)
class CheckItem:
    name: str
    ok: bool
    detail: str = ""
