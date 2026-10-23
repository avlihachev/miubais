---
title: Durable sessions and idempotency
description: How to restart a ticket without losing its conversation, paying for it twice or repeating its side effects, using resume and fork, error subtypes, budget headroom, idempotency keys and file checkpoints.
module: m1
order: 4
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/agent-sdk/sessions
    title: Work with sessions
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/agent-loop
    title: How the agent loop works
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/cost-tracking
    title: Track cost and usage
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/file-checkpointing
    title: Rewind file changes with checkpointing
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts
    title: Modifying system prompts
    checked: 2026-10-17
  - url: https://www.sqlite.org/lang_conflict.html
    title: SQLite, The ON CONFLICT clause
    checked: 2026-10-17
  - url: https://www.sqlite.org/lockingv3.html
    title: SQLite, File locking and concurrency in SQLite version 3
    checked: 2026-10-17
---

**Prerequisites:** [lesson 01](../01-harness-is-loop-plus-policy/) for the ticket runner this lesson makes restartable, and the SDK page [Work with sessions](https://code.claude.com/docs/en/agent-sdk/sessions) if `resume` is new to you.

## Why this matters for the factory

An unattended runner gets killed. A deploy replaces the worker, a container runs out of memory, a laptop sleeps, a cap ends the run halfway through a ticket. If the runner starts every retry from scratch, each restart pays again for the exploration the agent already did: the course's own build-time run of `tinyshop` ticket 001 took 8 assistant messages and about 0.21 USD, and a blind restart pays most of that a second time. If the runner retries carelessly, it repeats side effects: a second pull-request comment, a ticket moved twice, a deploy triggered twice.

Durability is three separate problems with three separate owners. The conversation lives in a session transcript that Claude Code writes to disk. The files live in the working tree, which git and file checkpoints can restore. Effects in other systems live in those systems and can only be made safe by idempotency keys. A harness that treats them as one thing and reruns the whole ticket gets all three wrong.

## Core idea

| what | owner | recover with | failure if ignored |
| --- | --- | --- | --- |
| conversation | `~/.claude/projects/.../<session-id>.jsonl` | `resume=<session_id>`, or a fresh session + notes | rerun pays twice; stale id fails the retry |
| files | working tree (git) | worktree per ticket, `rewind_files(checkpoint)` | half-applied edits stay |
| effects | other systems (API, DB) | idempotency key per op | duplicate comment, deploy |

A session is the conversation history: prompt, tool calls, tool results and responses. The sessions page is explicit that sessions persist the conversation, not the filesystem, and that forking branches the conversation while file edits stay real for anyone working in the same directory (Work with sessions). So a resumed ticket remembers that it already edited `pricing.py`, and the edit is still on disk because nothing undid it. That is usually what you want. It is not what you want when the previous attempt went wrong, which is why files get their own recovery path.

The rule for the harness is: store the session id per ticket, try to resume it, and fall back to a fresh session when the resume fails, recording that it did. Separately, every tool with an outside effect takes a key derived from the ticket and the operation, and executes at most once per key.

## Mechanics

### Session options and the UUID rule

`query()` creates a new session per call unless you pass `continue_conversation=True` or `resume` (Agent SDK reference - Python). The options mean different things:

- `resume=<id>` returns to that exact session with its full history. You must have stored the id.
- `continue_conversation=True` picks the most recent session in the current directory (Work with sessions). It needs no id, which makes it convenient for one conversation at a time and wrong for a runner that handles several tickets in the same `cwd`: "most recent" may be another ticket.
- `fork_session=True` together with `resume` starts a new session with a copy of the original's history and a new id; the original stays as it was. The standalone `fork_session()` function adds that the fork does not include the original session's file checkpoints, so you cannot rewind it to a checkpoint taken before the fork (Agent SDK reference - Python).
- `session_id=<id>` makes the SDK use your id instead of generating one. It must be a valid UUID, and it cannot be combined with `continue_conversation` or `resume` unless `fork_session` is also set (Agent SDK reference - Python). A ticket name is not a UUID: when we passed `session_id="ticket-001"` on 2026-10-17 with SDK 0.2.168, the CLI printed `Invalid session ID. Must be a valid UUID.` and the SDK raised a `ProcessError`. If you want ids you can derive, use `uuid.uuid5` over the ticket name and attempt number.

Read the id from `ResultMessage.session_id`, which is present on every result, success or error (Work with sessions). Store it on error results too: the sessions page lists "recover from a limit" as a reason to resume, after `error_max_turns` or `error_max_budget_usd`, with a higher limit. Session files live under `~/.claude/projects/<encoded-cwd>/` on the machine that created them; to resume on another host, use a session store adapter, move the file, or skip resume and pass the facts you need into a fresh prompt (Work with sessions).

One more thing travels with a session: its system prompt. Claude Code records the prompt on the session's first request and reuses it until the session is compacted, so a changed `append` or custom prompt passed on `resume` is not seen on the next turn (Modifying system prompts). If you change the runner's instructions in a deploy, tickets resumed afterwards keep the old ones.

### What a stale resume looks like

The docs do not describe the failure when the id points at nothing. We checked: resuming a random UUID with SDK 0.2.168 on 2026-10-17 yielded no messages and raised `ResultError` (a `ProcessError` subclass added in Python SDK 0.2.140) with `subtype` `error_during_execution`, `errors` `["No conversation found with session ID: ..."]` and `terminal_reason` `None`. No model call was made. Because the shape is undocumented and could change, the harness classifies by position rather than by message: a failure that happens before the first `AssistantMessage`, whether raised or returned as an `error_*` result, is a failed resume, and the runner retries once with `resume=None`. A failure after the agent has started working is a real run failure, and retrying it with a fresh session would pay for the work again.

The sample drives `run_resuming` from the lesson helpers with a scripted `query_fn` that fails the way the real SDK did. Run it with `PYTHONPATH=course/m1-harness-lab/starter/src:course/m1-harness-lab/lesson_support/src uv run --frozen python site/samples/m1/04-1.py`; nothing calls a model.

Sample: `site/samples/m1/04-1.py`.

```python
import asyncio
import uuid

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    TextBlock,
)
from harness_lab_lessons import run_resuming

STALE = "3f6c1b2a-9d4e-4c7b-8a1f-0e2d5c6b7a89"
FRESH = "8d0e7a41-52c3-4f9b-b6e2-1a7c9d3f5e60"
store = {"001-discount-rounding": STALE}


async def scripted_query(prompt, options):
    if options.resume == STALE:
        missing = f"No conversation found with session ID: {STALE}"
        raise ResultError(
            f"Claude Code returned an error result: {missing}",
            {"subtype": "error_during_execution", "errors": [missing], "session_id": STALE},
            exit_code=1,
        )
    yield AssistantMessage([TextBlock("Reading the ticket again from the start.")], model="m")
    yield ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=FRESH,
        terminal_reason="completed",
    )


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


options = ClaudeAgentOptions(cwd="/work/tinyshop", resume=store["001-discount-rounding"])
run = asyncio.run(run_resuming("Fix ticket 001.", options, scripted_query))
for number, attempt in enumerate(run.attempts, 1):
    print(f"attempt {number}: resume={attempt.resume} -> {attempt.outcome}")

result = run.messages[-1]
store["001-discount-rounding"] = result.session_id
print("result:", result.subtype, "new session:", result.session_id)
print("store now:", store)
print("valid session_id values:", {v: is_uuid(v) for v in ("ticket-001", FRESH)})
```

Output, run on 2026-10-17:

```
attempt 1: resume=3f6c1b2a-9d4e-4c7b-8a1f-0e2d5c6b7a89 -> ResultError: Claude Code returned an error result: No conversation found with session ID: 3f6c1b2a-9d4e-4c7b-8a1f-0e2d5c6b7a89 (exit code: 1)
attempt 2: resume=None -> ran
result: success new session: 8d0e7a41-52c3-4f9b-b6e2-1a7c9d3f5e60
store now: {'001-discount-rounding': '8d0e7a41-52c3-4f9b-b6e2-1a7c9d3f5e60'}
valid session_id values: {'ticket-001': False, '8d0e7a41-52c3-4f9b-b6e2-1a7c9d3f5e60': True}
```

The first attempt carries the stored id and fails before any assistant message, so the helper retries once without `resume` and records both attempts. The store is then updated with the new session's id, which is the step that is easy to forget: without it, every later restart of this ticket fails the same way first. The last line is the UUID rule from the previous section.

### Limits, subtypes and `terminal_reason`

A run ends with one of five subtypes: `success`, `error_max_turns`, `error_max_budget_usd`, `error_during_execution` and `error_max_structured_output_retries` (How the agent loop works). A single-shot `query()` yields the final result and then raises; the docs call the raise intentional, so wrap the loop in `try` if your code continues past it. `subtype` alone is not enough. When the final API request fails, Claude Code reports `subtype` `success` and puts the cause in `terminal_reason`, for example `api_error`; the reference says to check `terminal_reason` before `subtype` (Agent SDK reference - Python). `aborted_streaming` and `aborted_tools` mean the turn was cut off, typically by `interrupt()` or a permission callback that denied with `interrupt=True`.

`max_budget_usd` is compared against a client-side estimate after each model response arrives. The response that crosses the cap still completes and counts, so spend can pass the cap by the cost of that response plus whatever running subagents spend before they stop (How the agent loop works). Leave headroom: if a ticket must never cost more than 1.00 USD, set the cap below that by at least one large turn. The estimates are computed from a price table bundled with the SDK and are not billing data (Track cost and usage).

Resume changes the arithmetic. A resumed call's `total_cost_usd` includes the session's earlier spend (Claude Code v2.1.277 and later restore it from the transcript when the earlier process exited normally), while `max_budget_usd` counts only the call's own spend (Track cost and usage). A report that compares `total_cost_usd` with the cap will call a resumed run over budget when it is not. Keep the previous total per ticket and subtract it. The exercise does this: the stage 03 session table stores each ticket's last `total_cost_usd` in a `cost_usd` column, the stage 08 runner passes that stored total to `summarise(..., previous_cost_usd=...)` when the session really resumed (a fresh fallback subtracts nothing), and stage 05 compares only the difference with the cap. The lesson helper `summarise_messages` takes the same `previous_cost_usd` argument.

### Idempotent tools

A retry replays the agent's intent, not its exact calls: the model may call your custom `post_comment` tool again in the fresh session, or twice in one session. The tool, not the model, must make the second call harmless. Two designs exist.

- **Compute then insert.** Run the effect, then `INSERT OR IGNORE` the result under the key and read back whatever row is stored. A crash between the effect and the insert, or two workers racing, runs the effect twice; the database just agrees afterwards on one result. This is at-least-once, which is fine for effects that are naturally idempotent, such as writing a file with fixed content.
- **Claim before run.** `INSERT OR IGNORE` a claim row first. Only the connection whose insert took effect runs the effect, then records the outcome. Everyone else reads the row. This is at-most-once, and its failure mode is the opposite: a crash after the claim leaves a row that says `claimed` with no outcome, which a person or a reconciler has to resolve.

The guarantee comes from the constraint, not from your code's ordering. On a `PRIMARY KEY` or `UNIQUE` violation, SQLite's `IGNORE` algorithm skips the row and returns no error (SQLite, The ON CONFLICT clause), and SQLite lets only one connection write at a time (SQLite, File locking and concurrency in SQLite version 3), so of two concurrent claims exactly one inserts. The limit is the edge of the database: the effect itself happens in another system, outside the transaction, and no local table can tell you whether a request that timed out was applied. Where the remote API accepts its own idempotency key, pass the same key through.

The key must be stable across retries: ticket id plus operation name works; `tool_use_id` does not, because every attempt gets new ones.

Run the second sample the same way, with `site/samples/m1/04-2.py`. It uses `EffectLog`, the claim-before-run helper.

Sample: `site/samples/m1/04-2.py`.

```python
import tempfile
from pathlib import Path

from harness_lab_lessons import EffectLog

calls = []


def post_pr_comment() -> str:
    calls.append("POST /pulls/17/comments")
    return "comment 9001"


def flaky_deploy() -> str:
    raise ConnectionError("connection reset after the request was sent")


def show(label: str, effect) -> None:
    print(f"{label:<26} ran={effect.ran!s:<5} state={effect.state} outcome={effect.outcome}")


with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "effects.sqlite"
    log = EffectLog(db)
    for label in ("first call", "retry in the same process"):
        show(label, log.claim_then_run("001-discount-rounding:pr-comment", post_pr_comment))
    log.close()

    log = EffectLog(db)
    show("after a restart", log.claim_then_run("001-discount-rounding:pr-comment", post_pr_comment))
    print("side effect executed once" if len(calls) == 1 else f"executed {len(calls)} times")

    try:
        log.claim_then_run("001-discount-rounding:deploy", flaky_deploy)
    except ConnectionError as err:
        print("deploy raised:", err)
    show("deploy retry", log.claim_then_run("001-discount-rounding:deploy", flaky_deploy))
    log.close()
```

Output, run on 2026-10-17:

```
first call                 ran=True  state=done outcome=comment 9001
retry in the same process  ran=False state=done outcome=comment 9001
after a restart            ran=False state=done outcome=comment 9001
side effect executed once
deploy raised: connection reset after the request was sent
deploy retry               ran=False state=claimed outcome=None
```

The comment is posted once across a retry and a restart, and the second and third calls get the stored outcome. The deploy shows the price of at-most-once: the effect raised after the claim, so the retry neither runs it again nor knows whether the remote side acted. That `claimed` row is the signal to stop the ticket and ask, which is better than a second deploy.

### File checkpoints and `rewind_files`

With `enable_file_checkpointing=True`, the SDK backs up files before the Write, Edit and NotebookEdit tools modify them, and each user message in the stream carries a UUID that serves as a restore point; to receive those UUIDs, pass `extra_args={"replay-user-messages": None}`. `ClaudeSDKClient.rewind_files(user_message_id)` restores the tracked files to that point, deleting files the agent created. It does not rewind the conversation (Rewind file changes with checkpointing). The limits matter for a ticket runner: changes made through Bash, such as `sed -i` or a redirect, are not tracked; edits applied by subagents are not tracked; creating, moving or deleting directories is not undone. Treat checkpoints as an in-session undo before a risky step, and keep a git worktree per ticket as the real one.

## Common pitfalls

- **`continue_conversation` in a multi-ticket runner.** It resumes the most recent session in the directory, which can belong to another ticket. Store ids per ticket and pass `resume`.
- **Storing the session id only on success.** Error results carry `session_id` too, and resuming with a higher limit after `error_max_turns` is the cheap path. Store it whatever the subtype.
- **Retrying every failure with a fresh session.** Only failures before the first assistant message are resume failures. Retrying a run that already worked pays for it twice and can repeat its effects.
- **Comparing a resumed run's `total_cost_usd` with the cap.** It includes earlier spend; the cap does not. Subtract the stored previous total.
- **Idempotency keys built from `tool_use_id`.** They change on every attempt, so nothing is ever deduplicated. Derive keys from the ticket and the operation.
- **Expecting `rewind_files` to undo a Bash edit.** Only Write, Edit and NotebookEdit changes are tracked. Reset the worktree with git instead.

## What interviewers ask

**How do you make an agent run survive a process restart?**
Store the session id from every `ResultMessage` against the ticket and pass it as `resume` on restart, with one fallback to a fresh session when the resume fails before any assistant output. Keep files in a worktree per ticket and route outside effects through idempotent tools, because the session only restores the conversation.

**What is the difference between `resume`, `continue_conversation` and `fork_session`?**
`resume` returns to a specific session by id, while `continue_conversation` takes the most recent session in the working directory. `fork_session` with `resume` copies the history into a new session id and leaves the original unchanged, without its file checkpoints.

**Why can a run that hit `max_budget_usd` cost more than the cap?**
The SDK checks the estimate after each response arrives, so the response that crosses the cap still completes, and running subagents spend until they stop. Set the cap with headroom below the real limit and treat the figure as an estimate, not billing data.

**How do you make a tool call idempotent?**
Give each effect a stable key from the ticket and operation, and claim the key with an atomic insert before running the effect, so concurrent or repeated calls read the stored outcome. A crash after the claim leaves an unresolved row, which you surface rather than retry, and you pass the key to the remote API when it supports idempotency keys.

**When would you use `rewind_files` and when git?**
`rewind_files` undoes Write, Edit and NotebookEdit changes inside a session back to a user-message checkpoint, which suits a quick rollback before a risky step. It misses Bash edits, subagent edits and directory changes, so a factory still resets a per-ticket worktree with git.

## Sources

- [Work with sessions](https://code.claude.com/docs/en/agent-sdk/sessions), checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), checked 2026-10-17
- [How the agent loop works](https://code.claude.com/docs/en/agent-sdk/agent-loop), checked 2026-10-17
- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), checked 2026-10-17
- [Rewind file changes with checkpointing](https://code.claude.com/docs/en/agent-sdk/file-checkpointing), checked 2026-10-17
- [Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts), checked 2026-10-17
- [SQLite, The ON CONFLICT clause](https://www.sqlite.org/lang_conflict.html), checked 2026-10-17
- [SQLite, File locking and concurrency in SQLite version 3](https://www.sqlite.org/lockingv3.html), checked 2026-10-17
- Course code and records (repository files, not web sources): the lesson helpers in `course/m1-harness-lab/lesson_support/src/harness_lab_lessons/`; the stage 08 run made while this stage was built; its numbers are in `course/m1-harness-lab/README.md`, not in a committed record; the stale-resume and non-UUID probes were run against SDK 0.2.168 on 2026-10-17
