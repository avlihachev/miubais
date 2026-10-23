from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from harnesskit.hooks import HookCallback
from harnesskit.policy import Policy
from harnesskit.report import RunReport
from harnesskit.runner import QueryFn
from harnesskit.sessions import SessionStore

from injection_lab.audit import AuditLog
from injection_lab.provenance import Taint

MODEL = "claude-opus-5-5"
MAX_TURNS = 12
MAX_BUDGET_USD = 0.75


@dataclass
class HardenedRun:
    repo: Path
    policy: Policy
    taint: Taint
    log: AuditLog
    pre_tool_use: HookCallback
    post_tool_use: HookCallback
    run_id: str = field(default="")

    def guarded(self, query_fn: QueryFn | None = None) -> QueryFn:
        raise NotImplementedError

    def run(
        self,
        ticket: Path,
        *,
        store: SessionStore,
        query_fn: QueryFn | None = None,
        model: str = MODEL,
    ) -> RunReport:
        raise NotImplementedError


def stack(
    repo: Path, *, audit_path: Path, approval: Callable[[dict], bool] | None = None
) -> HardenedRun:
    raise NotImplementedError
