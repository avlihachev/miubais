---
title: M1 Enforced harness
freshness: skip
---

Hooks, permissions, subagents and durable sessions that make an agent harness enforce rather than suggest.

## Lessons

- [01 A harness is a loop plus a policy](./01-harness-is-loop-plus-policy/)
- [02 Hooks, permissions and modes](./02-hooks-permissions-and-modes/)
- [03 Subagents](./03-subagents/)
- [04 Durable sessions and idempotency](./04-durable-sessions-and-idempotency/)
- [05 Context engineering for code tasks](./05-context-engineering-for-code-tasks/)
- [06 Failure taxonomy and caps](./06-failure-taxonomy-and-caps/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M1 enforced harness lab](/exercises/m1-harness-lab/): build your own enforced harness around the Agent SDK, with tests and hints.

1. `01-policy-engine`: a `Guard` that decides what a tool call may do under writable roots and blocked command patterns.
2. `02-hook-adapter`: the guard wired as a `PreToolUse` hook that denies on any doubt, including its own errors.
3. `03-session-store`: durable ticket sessions with a fresh-session fallback when a resume fails.
4. `04-idempotent-tools`: side effects that run once per key, across restarts.
5. `05-caps-and-report`: turn and budget caps and a run summary that says why the run stopped.
6. `06-subagent-verdict`: a read-only reviewer subagent whose verdict is validated against a schema.
7. `07-failure-taxonomy`: classify harness failures from recorded traces (judgment stage).
8. `08-live-ticket`: one tinyshop ticket end to end against the real Agent SDK (needs a Claude login).
