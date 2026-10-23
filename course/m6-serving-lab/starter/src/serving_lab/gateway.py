from collections.abc import Callable
from typing import Literal

from serving_lab.types import ChatRequest, ChatResult, Route, RouteStats

HEALTH_TIMEOUT_S = 1.0
MAX_TURNS = 1
MAX_BUDGET_USD = 0.05


class Gateway:
    def __init__(
        self,
        routes: list[Route],
        *,
        prefer: Literal["local", "api"] = "local",
        query_fn: Callable | None = None,
        timeout_s: float = 30.0,
        health_path: str = "/health",
        extra_body: dict | None = None,
    ) -> None:
        raise NotImplementedError

    def chat(self, req: ChatRequest) -> ChatResult:
        raise NotImplementedError

    def stats(self) -> list[RouteStats]:
        raise NotImplementedError

    def to_markdown(self) -> str:
        raise NotImplementedError
