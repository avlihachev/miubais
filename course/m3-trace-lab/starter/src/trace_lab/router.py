from collections.abc import Callable
from pathlib import Path
from typing import Any

from harnesskit.report import RunReport
from harnesskit.runner import run_ticket
from opentelemetry.sdk.trace import TracerProvider

from trace_lab.types import Route, Routed, RouteStats

__all__ = ["Route", "Router"]


class Router:
    def __init__(
        self,
        routes: list[Route],
        *,
        fallback_on: frozenset[str] = frozenset({"budget", "max_turns", "error"}),
        tracer_provider: TracerProvider | None = None,
    ) -> None:
        self.routes = routes
        self.fallback_on = fallback_on
        self.tracer_provider = tracer_provider
        self.stats: dict[str, RouteStats] = {}

    def run(
        self,
        ticket_path: Path,
        repo: Path,
        *,
        run_fn: Callable[..., RunReport] = run_ticket,
        **kwargs: Any,
    ) -> Routed:
        raise NotImplementedError

    def to_markdown(self) -> str:
        raise NotImplementedError
