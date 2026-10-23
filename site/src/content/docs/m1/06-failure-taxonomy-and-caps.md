---
title: Failure taxonomy and caps
description: Eight ways an unattended coding agent fails, the tell for each in a trace, the caps that bound them (max_turns, max_budget_usd, Stop hooks, PreToolUse budget guards, timeouts), and what to measure per ticket to see them across a fleet.
module: m1
order: 6
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/agent-sdk/agent-loop
    title: How the agent loop works
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/hooks
    title: Intercept and control agent behavior with hooks
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/hooks
    title: Hooks reference
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/cost-tracking
    title: Track cost and usage
    checked: 2026-10-17
  - url: https://www.anthropic.com/engineering/building-effective-agents
    title: Building effective agents
    published: 2024-12-19
    checked: 2026-10-17
  - url: https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk
    title: Building agents with the Claude Agent SDK
    published: 2025-09-29
    checked: 2026-10-17
---

**Prerequisites:** [lesson 04](../04-durable-sessions-and-idempotency/), which covers the result subtypes, `terminal_reason` and budget headroom that this lesson turns into caps and metrics.

## Why this matters for the factory

Failed runs across a fleet are a cost line, and you can only shrink it if you can name the ways runs fail. "The agent failed" tells you nothing about whether to raise a cap, tighten a policy, rewrite a prompt or add a check. A taxonomy turns transcripts into counts, and counts into a decision: which fix removes the most wasted spend per week.

Caps are the other half. "Building effective agents" notes that agents bring higher costs and "the potential for compounding errors", and that it is common to include stopping conditions, such as a maximum number of iterations, to maintain control. Every failure mode below either burns turns, burns money, or ends with a false claim of success. Caps bound the first two. Only measurement outside the agent catches the third.

## Core idea

Classify by what the trace shows, not by what the final message says. The agent's last paragraph is not evidence, because every failure mode below can end with a confident summary. The categories are the ones the exercise's stage 07 uses; the wording here is this lesson's own.

- **loop.** The run keeps issuing the same calls, or swings back and forth between two edits, and each round returns what the last one did. Nothing is learned, yet every round costs a turn and money, so only a cap ends it. *Tell:* recurring tool inputs with recurring results, ending in a turn or budget stop.
- **scope-creep.** Besides the requested fix, the diff carries work no one requested: a rename here, a new helper module there, a tidy-up of a file the ticket never mentions. Whether or not the fix is right, the change can no longer be reviewed as one ticket. *Tell:* changed files outside the area the ticket points at, often justified in passing.
- **silent-skip.** A step the ticket requires, such as running the acceptance check, does not happen, or happens and fails without the agent noticing, and the run still says it is done. *Tell:* a missing, erroring or empty test run followed by a closing message that the tests pass.
- **policy-denied-retry.** After a denial, the agent goes after the very thing it was refused by another route: a different tool, a different spelling of the path, a different command. Accepting the denial and solving the problem another, permitted way is healthy and does not count. *Tell:* repeated denials around one target, or a refused action reappearing in a new form.
- **tool-result-poisoning.** Something the agent read, such as a comment, a log line or a command's output, is phrased as an instruction, and the agent obeys it as though the person who filed the ticket had written it. The resulting change has no basis in the ticket. *Tell:* the agent justifying an action by pointing at text it found in the repository or in output.
- **budget-blowout.** Spend grows far beyond what the ticket warrants, through whole-file reads of large files, enormous command output or repeated slow runs. The run hits the budget cap while the actual fix is tiny, half-done or never checked. *Tell:* a handful of very costly turns with large tool results, ending in `error_max_budget_usd`.
- **context-loss.** Something the agent knew earlier, a fact or the goal itself, drops out, for example after compaction, and the agent proceeds on an outdated picture. *Tell:* a later statement that contradicts an earlier correct one, or a switch to another ticket or file mid-run.
- **success.** The ticket was fixed and checked, even when some line in the trace resembles a failure: a denial, a first attempt that failed, a read that seems unnecessary. It earns a category because calling it a failure sends you to repair a harness that did its job. *Tell:* the acceptance test ran after the final edit and passed, and the diff stays within the ticket.

The tells overlap, so read in order: first the result subtype and `terminal_reason`, then the acceptance check, then the diff, then the denials, and only then the narrative.

To practise on something that is not one of the exercise traces, here is an invented excerpt from a different agent altogether: one that publishes a documentation site, with a policy that allows deploys to `staging` only. The line format matches the exercise's.

```
{"n": 4, "role": "assistant", "tool": "Bash", "input": {"command": "docs-cli deploy --env production"}}
{"n": 5, "role": "tool", "output": "denied: deploys are allowed to staging only"}
{"n": 6, "role": "assistant", "tool": "Bash", "input": {"command": "DOCS_ENV=production docs-cli deploy"}}
{"n": 7, "role": "tool", "output": "denied: deploys are allowed to staging only"}
{"n": 8, "role": "assistant", "tool": "Bash", "input": {"command": "docs-cli promote --from staging --to production"}}
```

Decide which category it belongs to using the tells above, then ask the counterfactual: if line 6 had been `docs-cli deploy --env staging` and the run had ended with a link check passing on staging, what would the same line 5 denial mean? The point of the exercise is that one line rarely decides the category; the lines after it do.

## Mechanics

### `max_turns` and `max_budget_usd`

`max_turns` caps tool-use round trips and `max_budget_usd` caps the estimated spend; both default to no limit, and hitting either returns a `ResultMessage` with `error_max_turns` or `error_max_budget_usd` (How the agent loop works). The budget is checked after each response arrives, so the run can pass the cap by up to one response plus whatever running subagents spend before they stop; the cap covers subagents, and once it is reached spawning another fails with `Budget limit reached`. Turn caps bound loops; budget caps bound blowouts; neither tells you which of the two you had; the trace and the metrics do.

### `Stop` hooks

A `Stop` hook runs when the main agent finishes responding. Returning `{"decision": "block", "reason": "..."}` keeps it going, with the reason as the explanation Claude receives (Hooks reference). That is the enforced counter to silent-skip: if your `PostToolUse` hook never saw the acceptance test run, or saw it fail, block the stop and say so. Two limits apply. The Python reference types `StopHookInput` with only `stop_hook_active` beyond the common fields (Agent SDK reference - Python), while the hooks reference also lists `last_assistant_message`, the text of Claude's final response (Hooks reference); either way, track "tests ran and passed" in your own state rather than trusting what the final message says; and Claude Code overrides the next block after eight consecutive continuations, a count that resets whenever Claude calls a tool (Hooks reference). Check `stop_hook_active` so a condition that can never be met does not loop the run. A timed-out `Stop` callback counts as no decision, so the agent stops (Intercept and control agent behavior with hooks). Any hook can also end the run outright with `continue_: False` and a `stopReason` (Agent SDK reference - Python).

### `PreToolUse` budget guards

`max_budget_usd` stops the run mid-thought. A softer limit below it, enforced in a `PreToolUse` hook, denies new tool calls with a reason such as "budget nearly spent: summarise what you changed and stop", so the agent finishes with a report instead of being cut off. The hook input carries no cost, so the guard reads a running estimate your own loop keeps from the message stream. Treat that estimate as approximate: per-step `output_tokens` on assistant messages is a placeholder, and the reliable total arrives on the result (Track cost and usage). Keep the hard cap as the backstop.

### Timeouts

Turns and dollars do not bound wall-clock time. Each hook callback has a timeout, set on `HookMatcher(timeout=...)`, defaulting to 600 seconds for most events; a timed-out `PreToolUse` blocks the tool call (Intercept and control agent behavior with hooks). API requests have their own: `API_TIMEOUT_MS` defaults to 600000 and `CLAUDE_CODE_MAX_RETRIES` to 10, both passed through `env`, and a stalled subagent is aborted after `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` (Agent SDK reference - Python). For a per-ticket deadline, run the ticket in a `ClaudeSDKClient` and call `interrupt()` when the deadline passes; the result then reports `terminal_reason` `aborted_streaming` or `aborted_tools`, which your report should map to a timeout rather than a success.

### What to measure per ticket

Five numbers per ticket, all read from outside the agent:

1. **Turns**: `num_turns` from the result. A run that ended without a result has no such field; count the distinct `message_id`s on its assistant messages instead, because one model response can arrive as several `AssistantMessage`s that share an id.
2. **Cost**: `total_cost_usd`, with `model_usage` for the split by model; remember from lesson 04 that a resumed call's total includes earlier spend.
3. **Denials**: `permission_denials` on the result plus the count your guard keeps itself, since the docs do not promise that hook denials appear in the list.
4. **Files changed**: from `git status` in the ticket's worktree, compared with the area the ticket names.
5. **Test result**: the acceptance test run by the harness after the agent stops, not the agent's claim.

Add why the run stopped, normalised from `subtype` and `terminal_reason`. "Building agents with the Claude Agent SDK" describes the agent loop as gather context, take action, verify work, repeat; the fifth number is the harness doing the verify step itself instead of trusting the agent's.

The sample runs three scripted runs through `summarise_messages` and prints them with `metrics_table`, both from the lesson helpers. The numbers are synthetic, and `cost_usd` in each row is the run's own spend (a resumed run would pass `previous_cost_usd` to subtract the restored total, as lesson 04 explains): the first mirrors the course's build-time live run of ticket 001 (about 0.21 USD, one file; that run's `num_turns` was not recorded, so the row uses its 8 assistant messages as the turn count), the second ends on `error_max_turns`, the third on `error_max_budget_usd` past a 0.75 USD cap. Run it with `PYTHONPATH=course/m1-harness-lab/starter/src:course/m1-harness-lab/lesson_support/src uv run --frozen python site/samples/m1/06-1.py`; nothing calls a model.

Sample: `site/samples/m1/06-1.py`.

```python
from collections import Counter

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from harness_lab_lessons import TicketMetrics, metrics_table, summarise_messages

MAX_TURNS, MAX_USD = 12, 0.75
SESSION = "11111111-2222-4333-8444-555555555555"


def run(assistant_turns: int, subtype: str, cost: float, denied: int) -> list:
    messages = [
        AssistantMessage([ToolUseBlock(f"toolu_{i:02}", "Read", {"file_path": "x.py"})], model="m")
        for i in range(assistant_turns - 1)
    ]
    messages.append(AssistantMessage([TextBlock("Done.")], model="m"))
    denials = [{"tool_name": "Edit", "tool_use_id": "toolu_00", "tool_input": {}}] * denied
    messages.append(
        ResultMessage(
            subtype=subtype,
            duration_ms=60_000,
            duration_api_ms=55_000,
            is_error=subtype != "success",
            num_turns=assistant_turns,
            session_id=SESSION,
            total_cost_usd=cost,
            permission_denials=denials,
            terminal_reason="completed" if subtype == "success" else None,
        )
    )
    return messages


tickets = [
    ("001-discount-rounding", run(8, "success", 0.21, 0), 1, True),
    ("002-negative-quantity", run(12, "error_max_turns", 0.48, 3), 2, False),
    ("003-out-of-stock-msg", run(10, "error_max_budget_usd", 0.79, 0), 0, None),
]
rows = [
    TicketMetrics(name, summarise_messages(messages, MAX_TURNS, MAX_USD), files, tests)
    for name, messages, files, tests in tickets
]
print(metrics_table(rows))
print("stopped_by:", dict(Counter(row.facts.stopped_by for row in rows)))
spent = sum(row.facts.cost_usd for row in rows)
shipped = sum(row.facts.stopped_by == "success" and row.tests_passed is True for row in rows)
print(f"spend ${spent:.2f}, shipped {shipped}, cost per shipped ticket ${spent / shipped:.2f}")
over = [row.ticket for row in rows if row.facts.cost_usd > MAX_USD]
print("over the cap:", over)
```

Output, run on 2026-10-17:

```
ticket                 stopped_by turns    cost denials files  tests
--------------------------------------------------------------------
001-discount-rounding  success        8   $0.21       0     1  pass
002-negative-quantity  max_turns     12   $0.48       3     2  fail
003-out-of-stock-msg   budget        10   $0.79       0     0  not run
stopped_by: {'success': 1, 'max_turns': 1, 'budget': 1}
spend $1.48, shipped 1, cost per shipped ticket $1.48
over the cap: ['003-out-of-stock-msg']
```

The rows are a triage list. The `max_turns` run has three denials and a failing test: look at its trace for policy-denied-retry or a loop before raising the cap. The budget run changed nothing and spent past its cap: the overshoot is the headroom problem from lesson 04, and zero files changed after ten turns suggests a blowout on reading rather than a hard fix. The last line is cost per shipped ticket: 1.48 USD spent for one shipped ticket, because the failed runs are paid for too.

### Reading the distribution

Over hundreds of tickets, look at shape rather than averages.

- **The share of each stop reason.** A rising `max_turns` share points at loops or tickets too big for one run; a rising budget share points at blowouts or a cap set too tight.
- **Turns and cost among successes,** as median and 90th percentile. Set `max_turns` and `max_budget_usd` from the 90th percentile of successful runs plus margin; caps far above that only buy longer failures.
- **Success with denials.** Each one is either a success that looks suspicious or a policy that was nearly bypassed. Sample them and read the traces.
- **Success with tests not run, or files outside scope.** These are silent-skips and scope-creep that the subtype counted as success. They should be zero; every one is a bug in the harness's verify step.
- **Cost per shipped ticket,** total spend divided by tickets whose acceptance test passed. It is the figure that moves when you fix the failure modes above, and the one that falls when you lower a cap that only funded failures.

## Common pitfalls

- **Reporting `success` from `subtype` alone.** An API failure on the final request also reports `success`; check `terminal_reason` first and run the acceptance test yourself.
- **Raising `max_turns` when runs hit it.** If the trace is a loop, more turns buy a longer loop. Classify first, then decide.
- **Counting only `permission_denials`.** Denials from your own guard may not appear there. Count them in the guard.
- **A `Stop` hook that blocks forever.** Without a `stop_hook_active` check, an unmeetable condition burns turns until the eight-continuation override ends it. Block once, then let it stop and mark the ticket failed.
- **Averages over all tickets.** A mean cost hides the tail where the money goes. Report percentiles and cost per shipped ticket.

## What interviewers ask

**How would you categorise failures of a coding agent running unattended?**
By what the trace shows: loops, scope creep, silently skipped verification, retrying around a policy denial, following instructions found in tool output, budget blowouts, and lost context, plus successes that only look suspicious. Each has a tell in the trace and a different fix, which is why a count by category is more useful than a failure rate.

**Which caps would you put on such an agent, and how do you set them?**
`max_turns` and `max_budget_usd` with headroom below the real limit, a soft budget guard in `PreToolUse`, a `Stop` hook that blocks stopping until verification has run, and a wall-clock deadline enforced with `interrupt()`. Set the numbers from the 90th percentile of successful runs plus margin, and revisit them as the distribution moves.

**How do you detect a run that claims success but did not verify its work?**
Do not take the claim: the harness runs the acceptance test after the agent stops and records the result separately from the subtype. A `Stop` hook can also refuse to let the agent finish until a `PostToolUse` hook has seen the test pass.

**What do you measure per ticket, and what do you report upward?**
Turns, cost with the model split, denials, files changed and the harness's own test result, plus the normalised stop reason. Upward goes the stop-reason distribution, percentiles of cost and turns, and cost per shipped ticket.

**A rising share of runs hit `max_turns`. What do you do?**
Sample those traces and classify them before touching the cap: loops and denied-retries need a policy or prompt fix, while tickets that genuinely need more steps need splitting or a higher cap. Raising the cap blindly mostly increases the cost of the failures.

## Sources

- [How the agent loop works](https://code.claude.com/docs/en/agent-sdk/agent-loop), checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), checked 2026-10-17
- [Intercept and control agent behavior with hooks](https://code.claude.com/docs/en/agent-sdk/hooks), checked 2026-10-17
- [Hooks reference](https://code.claude.com/docs/en/hooks), checked 2026-10-17
- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), checked 2026-10-17
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), published 2024-12-19, checked 2026-10-17
- [Building agents with the Claude Agent SDK](https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk), published 2025-09-29, checked 2026-10-17
- Course code and records (repository files, not web sources): the lesson helpers in `course/m1-harness-lab/lesson_support/src/harness_lab_lessons/`; the category definitions in `course/m1-harness-lab/README.md`; the stage 08 run made while the stage was built (numbers in the exercise README, not a committed record)
