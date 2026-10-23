import dataclasses
import re
import shlex
import sqlite3
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage

FILE_WRITERS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
READERS = ("Read", "Grep", "Glob")
BANNED_COMMANDS = (r"rm\s+-rf", r"git\s+push", r"\bsudo\b", r"curl .*\|\s*(ba)?sh")
REDIRECTION = re.compile(r"\d?>{1,2}(.*)")


@dataclass(frozen=True)
class Ruling:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class RunFacts:
    turns: int
    cost_usd: float
    stopped_by: str
    denials: int
    cost_by_model: dict[str, float] = field(default_factory=dict)


def _under(target: str, roots: list[Path], cwd: Path) -> bool:
    resolved = (cwd / target).resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


def _redirect_targets(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    tokens = list(lexer)
    targets = []
    for index, token in enumerate(tokens):
        match = REDIRECTION.fullmatch(token)
        if not match:
            continue
        rest = match.group(1) or (tokens[index + 1] if index + 1 < len(tokens) else "")
        if rest and not rest.startswith("&") and rest != "/dev/null":
            targets.append(rest)
    return targets


def decide(
    tool: str,
    args: dict,
    roots: list[Path],
    *,
    cwd: Path | None = None,
    banned: tuple[str, ...] = BANNED_COMMANDS,
) -> Ruling:
    cwd = cwd or roots[0]
    if tool in READERS:
        return Ruling(True, "reads have no side effects")
    if tool in FILE_WRITERS:
        target = args.get("file_path") or args.get("notebook_path") or ""
        if target and _under(target, roots, cwd):
            return Ruling(True, f"{target} resolves under an allowed root")
        return Ruling(False, f"{target or 'no path'} resolves outside every allowed root")
    if tool == "Bash":
        command = args.get("command", "")
        hit = next((p for p in banned if re.search(p, command)), None)
        if hit:
            return Ruling(False, f"command matches banned pattern {hit}")
        for target in _redirect_targets(command):
            if not _under(target, roots, cwd):
                return Ruling(False, f"output redirected to {target}, outside every allowed root")
        return Ruling(True, "no banned pattern, no redirect outside the roots")
    return Ruling(False, f"{tool} is not on the known list, denied by default")


def deny(event: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def review_verdict_schema() -> dict:
    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": ["file", "line", "severity", "note"],
        "properties": {
            "file": {"type": "string"},
            "line": {"type": "integer", "minimum": 1},
            "severity": {"enum": ["critical", "important", "minor"]},
            "note": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["approve", "findings"],
        "properties": {
            "approve": {"type": "boolean"},
            "findings": {"type": "array", "items": finding},
        },
    }


def summarise_messages(
    messages: list, max_turns: int, max_usd: float, previous_cost_usd: float = 0.0
) -> RunFacts:
    result = next((m for m in reversed(messages) if isinstance(m, ResultMessage)), None)
    if result is None:
        assistants = [m for m in messages if isinstance(m, AssistantMessage)]
        ids = {m.message_id for m in assistants if m.message_id}
        turns = len(ids) + sum(1 for m in assistants if not m.message_id)
        return RunFacts(turns, 0.0, "error", 0)
    cost = (result.total_cost_usd or 0.0) - previous_cost_usd
    if result.subtype == "error_max_budget_usd" or cost >= max_usd:
        stopped_by = "budget"
    elif result.subtype == "error_max_turns":
        stopped_by = "max_turns"
    elif result.subtype == "success" and result.terminal_reason in (None, "completed"):
        stopped_by = "success"
    else:
        stopped_by = "error"
    by_model = {name: u.get("costUSD", 0.0) for name, u in (result.model_usage or {}).items()}
    denials = len(result.permission_denials or [])
    return RunFacts(result.num_turns, cost, stopped_by, denials, by_model)


@dataclass(frozen=True)
class ResumeAttempt:
    resume: str | None
    outcome: str


@dataclass(frozen=True)
class ResumeRun:
    messages: list
    attempts: list[ResumeAttempt]


def _failure_text(exc: Exception) -> str:
    lines = str(exc).splitlines()
    return f"{type(exc).__name__}: {lines[0]}" if lines else type(exc).__name__


async def _drain(
    query_fn: Callable[[str, ClaudeAgentOptions], AsyncIterator[Any]],
    prompt: str,
    options: ClaudeAgentOptions,
) -> tuple[list, str | None]:
    messages: list = []
    try:
        async for message in query_fn(prompt, options):
            messages.append(message)
    except Exception as exc:
        if not any(isinstance(m, ResultMessage) for m in messages):
            if any(isinstance(m, AssistantMessage) for m in messages):
                raise
            return messages, _failure_text(exc)
    result = next((m for m in messages if isinstance(m, ResultMessage)), None)
    worked = any(isinstance(m, AssistantMessage) for m in messages)
    if result is not None and result.subtype.startswith("error_") and not worked:
        return messages, result.subtype
    return messages, None


async def run_resuming(
    prompt: str,
    options: ClaudeAgentOptions,
    query_fn: Callable[[str, ClaudeAgentOptions], AsyncIterator[Any]],
) -> ResumeRun:
    messages, failure = await _drain(query_fn, prompt, options)
    first = ResumeAttempt(options.resume, failure or "ran")
    if failure is None or options.resume is None:
        return ResumeRun(messages, [first])
    fresh = dataclasses.replace(options, resume=None, fork_session=False)
    messages, failure = await _drain(query_fn, prompt, fresh)
    return ResumeRun(messages, [first, ResumeAttempt(None, failure or "ran")])


@dataclass(frozen=True)
class Effect:
    state: str
    outcome: str | None
    ran: bool


class EffectLog:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS effects "
            "(op_key TEXT PRIMARY KEY, state TEXT NOT NULL, outcome TEXT)"
        )
        self.db.commit()

    def claim_then_run(self, key: str, fn: Callable[[], str]) -> Effect:
        claimed = self.db.execute(
            "INSERT OR IGNORE INTO effects (op_key, state) VALUES (?, 'claimed')", (key,)
        ).rowcount
        self.db.commit()
        if not claimed:
            state, outcome = self.db.execute(
                "SELECT state, outcome FROM effects WHERE op_key = ?", (key,)
            ).fetchone()
            return Effect(state, outcome, ran=False)
        outcome = fn()
        self.db.execute(
            "UPDATE effects SET state = 'done', outcome = ? WHERE op_key = ?", (outcome, key)
        )
        self.db.commit()
        return Effect("done", outcome, ran=True)

    def close(self) -> None:
        self.db.close()


@dataclass(frozen=True)
class TicketMetrics:
    ticket: str
    facts: RunFacts
    files_changed: int
    tests_passed: bool | None


def metrics_table(rows: list[TicketMetrics]) -> str:
    header = f"{'ticket':<22} {'stopped_by':<10} {'turns':>5} {'cost':>7} {'denials':>7} {'files':>5}  tests"
    lines = [header, "-" * len(header)]
    for row in rows:
        tests = {True: "pass", False: "fail", None: "not run"}[row.tests_passed]
        lines.append(
            f"{row.ticket:<22} {row.facts.stopped_by:<10} {row.facts.turns:>5} "
            f"{f'${row.facts.cost_usd:.2f}':>7} {row.facts.denials:>7} {row.files_changed:>5}  {tests}"
        )
    return "\n".join(lines)
