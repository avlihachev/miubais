# Hooks, permissions and modes

**Prerequisites:** [lesson 01](../01-harness-is-loop-plus-policy/), which sets out the permission flow and the four surfaces this lesson takes apart.

## Why this matters for the factory

A ticket runner fails in two directions. If the policy is too loose, an unattended agent edits tests, pushes branches or deletes files, and the cost is a bad merge or a cleanup job. If it is too tight, or wired wrong, runs stall on a prompt nobody answers, or burn turns retrying calls that will never be allowed, and the cost shows up as turns and dollars per ticket with nothing merged. Both failures come from the same place: a misunderstanding of which surface decides a given call, in which order, and what happens when two of them disagree.

This lesson is the reference you keep open while wiring a harness. It covers every hook event the Python SDK exposes, the callback contract to the field, the four `PreToolUse` decisions, how several hooks combine, timeouts, and how hooks relate to `can_use_tool`, the permission modes and the allow and deny rules.

## Core idea

Think of the harness as two layers with different jobs. Hooks are code: they see the real arguments of each call and can compute anything, such as a resolved path, a running cost or a lookup in your ticket system. Rules and modes are configuration: cheap, declarative, evaluated by Claude Code itself, and not able to express "this path resolves under `src/`" beyond a pattern. A sound harness uses configuration to shrink the surface (which tools exist, what is denied by pattern, what happens to anything nobody decided) and a hook to enforce the policy that needs code.

The order matters because it decides who can override whom. Hooks run first. A hook deny is final, even in `bypassPermissions`. A hook allow only skips the prompt: deny rules and ask rules are still evaluated after it, and the actions no mode auto-approves, such as an `rm` of a critical path, stay unapproved (Configure permissions; Choose a permission mode). `can_use_tool` sits at the very end and sees only what nothing else decided. In short:

```
 hook deny      > every rule and every mode
 deny rule      > hook allow, allow rules, bypassPermissions
 ask rule       > hook allow, allow rules (goes to can_use_tool; denied in dontAsk)
 mode           decides whatever the rules left open
 can_use_tool   last; never called in dontAsk or for auto-approved calls
```

## Mechanics

### The hook events available in Python

The SDK hooks page lists which events each SDK supports (Intercept and control agent behavior with hooks). In Python there are ten:

| Event | Fires when | Typical harness use |
| --- | --- | --- |
| `PreToolUse` | a tool call is requested; can block or modify it | the policy guard |
| `PostToolUse` | a tool returned a result | audit log; `additionalContext` or `updatedToolOutput` |
| `PostToolUseFailure` | a tool execution failed | count and log tool errors |
| `UserPromptSubmit` | a prompt is submitted | add context, or block a prompt |
| `Stop` | the main agent finishes responding | require a check before finishing |
| `SubagentStart` | a subagent is spawned or resumed | track fan-out |
| `SubagentStop` | a subagent completes | collect transcripts, aggregate results |
| `PreCompact` | compaction is about to run | archive the transcript first |
| `Notification` | the agent emits a status message | forward to chat or paging |
| `PermissionRequest` | a call needs a permission decision | decide on behalf of a user |

`SessionStart`, `SessionEnd` and other TypeScript-only events, such as `PostToolBatch` or `StopFailure`, are not available as Python callbacks. A Python app can still get `SessionStart` and `SessionEnd` as shell command hooks from a settings file when the matching `setting_sources` entry is enabled, because the SDK collects settings-file hooks alongside your callbacks (Intercept and control agent behavior with hooks).

### The callback contract

A callback is `async def cb(input_data, tool_use_id, context) -> dict`. All inputs share `session_id`, `cwd` and `hook_event_name`; the Python base input also carries `transcript_path` and, optionally, `permission_mode`. Tool events add `tool_name` and `tool_input`, whose keys depend on the tool: `file_path` for Read, Write and Edit, `command` for Bash, `pattern` and `path` for Grep and Glob. `tool_use_id` correlates the `PreToolUse` and `PostToolUse` events of one call. In Python, `context` is reserved for future use (Intercept and control agent behavior with hooks; Agent SDK reference - Python).

`PreToolUse` decisions go inside `hookSpecificOutput`:

```python
{}
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "why, for the model"}}
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": {**tool_input, "file_path": new_path}}}
```

The four values behave differently. `deny` blocks the call and the reason goes to Claude. `allow` skips the prompt but not the deny and ask rules. `ask` sends the call to the permission prompt, which in the SDK is your `can_use_tool` callback, with the hook's reason available as `context.decision_reason`; `dontAsk` turns that prompt into a denial. `defer` ends the turn with a result whose `stop_reason` is `"tool_deferred"` and whose `deferred_tool_use` carries the pending call, so the host can collect an answer and resume later (Hooks reference; Agent SDK reference - Python).

`updatedInput` replaces the whole input object, so copy the unchanged fields in. Paired with `allow` it auto-approves the rewritten call, with `ask` it shows the rewritten call, and without a decision it flows through normal evaluation; with `defer` it is ignored. Permission rules are evaluated against the input your hook returns, not the one Claude sent (Hooks reference). Return a new dict rather than mutating `tool_input`.

Other events use other fields. `PostToolUse` can return `additionalContext`, which is appended next to the tool result, or `updatedToolOutput`, which replaces the output before Claude sees it. `Stop` and `SubagentStop` can return `decision: "block"` with a `reason` to keep Claude working; the Hooks reference caps that at 8 consecutive continuations and passes `stop_hook_active` in the input so your hook can tell it is already in such a loop. Top-level `systemMessage` and `continue_` (spelled with a trailing underscore in Python) are accepted on every event.

### Several hooks, parallel execution and precedence

All matching hooks for an event run in parallel, and their completion order is not deterministic. For permission decisions the most restrictive wins: `deny` over `defer` over `ask` over `allow` (Intercept and control agent behavior with hooks). Write each hook so it is correct on its own; an audit hook must not assume the guard already ran.

A `HookMatcher(matcher=..., hooks=[...], timeout=...)` filters by the event's target: the tool name for tool events, the agent type for `SubagentStart`, the trigger for `PreCompact`; `Stop` ignores matchers. A pipe list such as `Write|Edit` is an exact list; a regex such as `^mcp__` matches MCP tools. Omit the matcher to run on every event of that type.

### Timeouts and asynchronous hooks

`timeout` is in seconds. The default is 600 seconds for most events and 30 for `UserPromptSubmit`. When a callback exceeds it, Claude Code cancels it and discards its output; for `PreToolUse` the call is blocked and Claude receives a tool result saying the hook did not respond in time, and for `Stop` and `SubagentStop` the timed-out callback counts as no decision (Intercept and control agent behavior with hooks). For side effects that should not delay the agent, return `{"async_": True}`, optionally with `asyncTimeout` in milliseconds; an async hook cannot block, modify or add context, because the agent has already moved on.

### Hooks against `can_use_tool`

`can_use_tool(tool_name, input, context)` returns `PermissionResultAllow(updated_input=..., updated_permissions=...)` or `PermissionResultDeny(message=..., interrupt=False)`. It is called only when the permission flow falls through to a prompt; a call approved by `allowed_tools`, a settings allow rule or the mode never reaches it, and `dontAsk` skips it (Agent SDK reference - Python; Configure permissions). The Python example in the user-input guide passes the prompt as an async generator and registers a placeholder `PreToolUse` hook that returns `{"continue_": True}`, which the guide calls a required workaround to keep the stream open for `can_use_tool` (Handle approvals and user input). Use hooks for policy that must see every call, and `can_use_tool` for human approval of what policy left open.

### Modes, allow and deny rules, settings

The six `permission_mode` values are `default`, `acceptEdits`, `plan`, `dontAsk`, `bypassPermissions` and `auto` (Configure permissions):

- `default`: no mode-based approvals; anything that needs approval and matches no allow rule goes to `can_use_tool`.
- `dontAsk`: every would-be prompt becomes a denial; pre-approved calls, hook-approved calls and calls that need no approval, such as reads inside the working directory and the `Agent` tool, still run.
- `acceptEdits`: approves edits and filesystem commands such as `mkdir`, `rm` and `mv` inside the working directory and added directories.
- `plan`: no edits are auto-approved, even with an allow rule; they prompt through `can_use_tool`.
- `bypassPermissions`: approves everything that reaches the mode step, whatever `allowed_tools` says; hooks, deny rules and ask rules still apply.
- `auto`: a classifier model reviews actions such as shell commands and network requests. The permission modes page lists the provider and model limits, and auto mode pauses after 3 blocks in a row or 20 in total.

If you set no mode, Claude Code picks the starting mode from settings or the built-in default, which can be auto mode; a session that starts in auto mode drops broad allow rules such as a bare `Bash`. Pass the mode explicitly (Configure permissions).

`allowed_tools` auto-approves the tools it names and restricts nothing. `disallowed_tools` with a bare name removes the tool from the request; with a scoped rule such as `"Bash(git push *)"` the tool stays and matching calls are denied in every mode, matched against the command as written. `setting_sources` controls which filesystem settings load: `None` loads user, project and local settings like the CLI does, `[]` loads none (Agent SDK reference - Python). For a harness, `[]` means a repository's `.claude/settings.json` cannot add allow rules or hooks to your run.

### Running a hook without a model

The sample calls a guard callback directly with two hand-built `PreToolUse` inputs and prints what it returns, then builds the `HookMatcher` and options a ticket runner would pass. It uses `decide` and `deny` from `course/m1-harness-lab/lesson_support/` (lesson helpers, not the exercise solution) and calls no model; run it with `PYTHONPATH=course/m1-harness-lab/starter/src:course/m1-harness-lab/lesson_support/src uv run --frozen python site/samples/m1/02-1.py`.

Sample: `site/samples/m1/02-1.py`.

```python
import asyncio
import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from harness_lab_lessons import decide, deny

ROOTS = [Path("/work/tinyshop/src")]


async def guard(input_data, tool_use_id, context):
    event = input_data.get("hook_event_name", "PreToolUse")
    try:
        ruling = decide(
            input_data["tool_name"],
            input_data.get("tool_input") or {},
            ROOTS,
            cwd=Path(input_data["cwd"]),
        )
    except Exception as exc:  # noqa: BLE001
        return deny(event, f"guard error: {exc}")
    return {} if ruling.allowed else deny(event, ruling.reason)


def pre_tool_use(tool_name: str, tool_input: dict) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "11111111-2222-4333-8444-555555555555",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/work/tinyshop",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "toolu_01",
    }


edit = pre_tool_use(
    "Edit",
    {
        "file_path": "/work/tinyshop/src/tinyshop/pricing.py",
        "old_string": "round(cents)",
        "new_string": "cents.quantize(CENT, rounding=ROUND_HALF_UP)",
    },
)
push = pre_tool_use("Bash", {"command": "git push origin main"})
for event in (edit, push):
    returned = asyncio.run(guard(event, event["tool_use_id"], None))
    print(event["tool_name"], "->", json.dumps(returned))

matcher = HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit|Bash", hooks=[guard], timeout=30)
options = ClaudeAgentOptions(
    cwd="/work/tinyshop",
    allowed_tools=["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
    disallowed_tools=["WebFetch", "Bash(git push *)"],
    permission_mode="dontAsk",
    hooks={"PreToolUse": [matcher]},
    setting_sources=[],
)
print("matcher:", matcher.matcher, "timeout:", matcher.timeout, "callbacks:", len(matcher.hooks))
print("mode:", options.permission_mode, "denied:", options.disallowed_tools)
print("settings loaded:", options.setting_sources)
```

Output, run on 2026-10-17:

```
Edit -> {}
Bash -> {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "command matches banned pattern git\\s+push"}}
matcher: Write|Edit|MultiEdit|NotebookEdit|Bash timeout: 30 callbacks: 1
mode: dontAsk denied: ['WebFetch', 'Bash(git push *)']
settings loaded: []
```

The Edit inside `src/` gets `{}`: the hook has no objection and the call continues to the rules and the mode, where `allowed_tools` approves it. The push gets the exact deny shape, with `hookEventName` copied from the input. The scoped `Bash(git push *)` rule duplicates the hook on purpose: if the hook is misregistered, the rule still denies the plain form of the command. Because a unit test can call the callback like this, the guard's behaviour is testable without spending a turn. In a live run a denial is not free: the response that asked for the call is already paid for, and the deny reason comes back as a tool result that the model answers on its next turn, so each denied attempt spends a turn of `max_turns` and its tokens. That is why the system prompt still states the rule the hook enforces.

The exercise's `guard_hook` (stage 02) is a `PreToolUse` adapter only. For any other event it returns `{}`, because the deny shape above belongs to `PreToolUse` and an event such as `PermissionRequest` has its own output shape; a later module may extend the adapter.

## Pitfalls seen in the wild

- **Returning `allow` for everything that passes.** A hook allow skips the prompt for calls nobody listed; return `{}` unless you mean to approve, and let `allowed_tools` and the mode decide the rest.
- **Forgetting `hookEventName` or putting `permissionDecision` at the top level.** The decision lives inside `hookSpecificOutput`; build it with one helper used by every hook.
- **Mutating `tool_input` for `updatedInput`.** The docs ask for a new object, and the replacement must include every field, or the tool runs without them.
- **Relying on hook order.** Hooks on one event run in parallel; an audit hook that reads state written by the guard sees it sometimes.
- **Using `can_use_tool` as the guard.** It never sees auto-approved calls and is skipped in `dontAsk`; without a streaming prompt and a placeholder hook it may not be called at all in Python.
- **Leaving `setting_sources` at its default in a harness.** A repository's own settings then load with your run; pass `[]` and put the policy in code.

## What interviewers ask

**What are the four `PreToolUse` decisions and how do they combine?**
`allow`, `deny`, `ask` and `defer`; across hooks the most restrictive wins, `deny` over `defer` over `ask` over `allow`. Even an `allow` from every hook does not override a deny rule or an ask rule.

**When would you use `updatedInput` instead of a deny?**
When the call is fine with a correction, such as redirecting a write into a sandbox directory or adding a safe flag. The replacement must be the complete input, and rules are evaluated against it, so a rewrite cannot slip past a deny rule.

**Your `can_use_tool` callback never fires. Why?**
The call was decided earlier: an allow rule, `acceptEdits` or `bypassPermissions` approved it, a hook or deny rule denied it, or the mode is `dontAsk`. In Python it also needs a streaming prompt and a placeholder `PreToolUse` hook to keep the stream open.

**What happens when a `PreToolUse` hook times out?**
Claude Code cancels it after its timeout (600 seconds by default), blocks the call and tells Claude the hook did not respond. Set a short explicit timeout so a hung dependency costs seconds, not ten minutes per call.

**Why pass `setting_sources=[]` in a headless runner?**
So that no user, project or local settings file adds allow rules, hooks or a default mode to the run; the policy is then exactly what the code says. Load `"project"` deliberately if you need `CLAUDE.md` or project rules.

## Sources

- [Intercept and control agent behavior with hooks](https://code.claude.com/docs/en/agent-sdk/hooks), checked 2026-10-17
- [Hooks reference](https://code.claude.com/docs/en/hooks), checked 2026-10-17
- [Configure permissions](https://code.claude.com/docs/en/agent-sdk/permissions), checked 2026-10-17
- [Choose a permission mode](https://code.claude.com/docs/en/permission-modes), checked 2026-10-17
- [Handle approvals and user input](https://code.claude.com/docs/en/agent-sdk/user-input), checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), checked 2026-10-17
- Course code (repository files, not web sources): the lesson helpers in `course/m1-harness-lab/lesson_support/src/harness_lab_lessons/`
