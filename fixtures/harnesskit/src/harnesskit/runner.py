import asyncio
import contextlib
import dataclasses
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    query,
)

from harnesskit.hooks import HookCallback, pre_tool_use
from harnesskit.policy import Policy
from harnesskit.report import RunReport, stopped_by_from
from harnesskit.sessions import SessionStore

QueryFn = Callable[[str, ClaudeAgentOptions], AsyncIterator[Any]]
Observer = Callable[[Any], bool | None]
TOOLS = ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]
SYSTEM_PROMPT = """You fix exactly one ticket in the repository in your working directory.
Read the ticket, find the cause in the source, and make the smallest change that fixes it.
Do not edit tests. Run the test command the ticket names and stop once it passes.
Finish with one short paragraph: what was wrong and what you changed."""


class TicketDone(Exception):
    pass


def default_query(prompt: str, options: ClaudeAgentOptions) -> AsyncIterator[Any]:
    return query(prompt=prompt, options=options)


@dataclasses.dataclass
class Attempt:
    result: ResultMessage | None = None
    assistants: list[AssistantMessage] = dataclasses.field(default_factory=list)
    error: Exception | None = None
    messages: list[Any] = dataclasses.field(default_factory=list)
    stopped_by_observer: bool = False

    @property
    def saw_assistant(self) -> bool:
        return bool(self.assistants)

    @property
    def turns(self) -> int:
        if self.result is not None:
            return self.result.num_turns
        ids = {m.message_id for m in self.assistants if m.message_id}
        return len(ids) + sum(1 for m in self.assistants if not m.message_id)

    def resume_failure(self) -> str | None:
        if self.saw_assistant:
            return None
        if self.result is not None:
            return self.result.subtype if self.result.subtype.startswith("error_") else None
        if self.error is not None:
            return str(self.error) or type(self.error).__name__
        return None


async def consume(
    query_fn: QueryFn,
    prompt: str,
    options: ClaudeAgentOptions,
    observer: Observer | None = None,
) -> Attempt:
    attempt = Attempt()
    observer_error: Exception | None = None
    try:
        async with contextlib.aclosing(query_fn(prompt, options)) as messages:
            async for message in messages:
                attempt.messages.append(message)
                if isinstance(message, AssistantMessage):
                    attempt.assistants.append(message)
                elif isinstance(message, ResultMessage):
                    attempt.result = message
                if observer is None:
                    continue
                try:
                    stop = observer(message)
                except Exception as exc:  # noqa: BLE001
                    observer_error = exc
                    break
                if stop:
                    attempt.stopped_by_observer = True
                    break
    except Exception as exc:  # noqa: BLE001 - any failure may be a stale resume
        attempt.error = exc
    if observer_error is not None:
        raise observer_error
    return attempt


def changed_files(repo: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line[3:].split(" -> ")[-1].strip('"') for line in proc.stdout.splitlines() if line]


async def run_ticket_async(
    ticket_path: Path,
    repo: Path,
    *,
    policy: Policy,
    store: SessionStore,
    max_turns: int = 12,
    max_budget_usd: float = 0.50,
    model: str | None = None,
    agents: dict | None = None,
    query_fn: QueryFn | None = None,
    observer: Observer | None = None,
    post_tool_use: HookCallback | None = None,
    extra_hooks: dict[str, list[HookCallback]] | None = None,
) -> RunReport:
    query_fn = query_fn or default_query
    ticket_id = Path(ticket_path).stem
    prompt = f"Ticket {ticket_id}:\n\n{Path(ticket_path).read_text()}"
    denials: list[dict] = []

    def audit(entry: dict) -> None:
        if not entry["allow"]:
            denials.append(entry)

    if agents:
        policy = dataclasses.replace(policy, passthrough=policy.passthrough | {"Agent"})
    stored = store.get(ticket_id)
    if stored is not None and stored.status == "done":
        raise TicketDone(f"{ticket_id} is done (session {stored.session_id}); not run again")
    hooks = {"PreToolUse": [HookMatcher(hooks=[pre_tool_use(policy, audit=audit)])]}
    if post_tool_use is not None:
        hooks["PostToolUse"] = [HookMatcher(hooks=[post_tool_use])]
    for event, callbacks in (extra_hooks or {}).items():
        if callbacks:
            hooks.setdefault(event, []).append(HookMatcher(hooks=list(callbacks)))
    options = ClaudeAgentOptions(
        cwd=repo,
        allowed_tools=TOOLS + ["Agent"] if agents else list(TOOLS),
        permission_mode="dontAsk",
        hooks=hooks,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        resume=stored.session_id if stored else None,
        setting_sources=[],
        system_prompt=SYSTEM_PROMPT,
        agents=agents,
        model=model,
    )
    attempt = await consume(query_fn, prompt, options, observer)
    resumed, notes = stored is not None, []
    if stored is not None and (reason := attempt.resume_failure()):
        denials.clear()
        resumed, notes = False, [f"resume failed: {reason}; started fresh"]
        attempt = await consume(
            query_fn, prompt, dataclasses.replace(options, resume=None), observer
        )

    result = attempt.result
    if attempt.stopped_by_observer and result is None:
        seen = [m.session_id for m in attempt.assistants if m.session_id]
        return RunReport(
            ticket_id=ticket_id,
            session_id=seen[-1] if seen else None,
            turns=attempt.turns,
            cost_usd=getattr(observer, "cost_usd", 0.0),
            stopped_by="budget",
            files_changed=changed_files(repo),
            tests_passed=None,
            verdict=None,
            resumed=resumed,
            notes=notes + ["stopped by observer"],
            messages=attempt.messages,
        )
    if result is None:
        why = f"run failed: {attempt.error}" if attempt.error else "run ended without a result"
        return RunReport(
            ticket_id=ticket_id,
            session_id=None,
            turns=attempt.turns,
            cost_usd=0.0,
            stopped_by="error",
            files_changed=changed_files(repo),
            tests_passed=None,
            verdict=None,
            resumed=resumed,
            notes=notes + [why],
            messages=attempt.messages,
        )

    total = result.total_cost_usd or 0.0
    cost = total - (stored.cost_usd if resumed else 0.0)
    budget_hit = result.subtype == "error_max_budget_usd" or cost >= max_budget_usd
    stopped_by = stopped_by_from(result, budget_hit)
    if stopped_by == "error" and denials:
        stopped_by = "policy"
    status = "done" if stopped_by == "success" else "open"
    store.put(ticket_id, result.session_id, status=status, cost_usd=total)
    return RunReport(
        ticket_id=ticket_id,
        session_id=result.session_id,
        turns=attempt.turns,
        cost_usd=cost,
        stopped_by=stopped_by,
        files_changed=changed_files(repo),
        tests_passed=None,
        verdict=None,
        resumed=resumed,
        notes=notes,
        messages=attempt.messages,
    )


def run_ticket(
    ticket_path: Path,
    repo: Path,
    *,
    policy: Policy,
    store: SessionStore,
    max_turns: int = 12,
    max_budget_usd: float = 0.50,
    model: str | None = None,
    agents: dict | None = None,
    query_fn: QueryFn | None = None,
    observer: Observer | None = None,
    post_tool_use: HookCallback | None = None,
    extra_hooks: dict[str, list[HookCallback]] | None = None,
) -> RunReport:
    return asyncio.run(
        run_ticket_async(
            ticket_path,
            repo,
            policy=policy,
            store=store,
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            model=model,
            agents=agents,
            query_fn=query_fn,
            observer=observer,
            post_tool_use=post_tool_use,
            extra_hooks=extra_hooks,
        )
    )
