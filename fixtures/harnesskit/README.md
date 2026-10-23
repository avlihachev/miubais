# harnesskit

The shared harness primitives later modules build on: a tool policy, Agent SDK hook adapters, a
SQLite session store per ticket, an idempotency wrapper, a run report and a thin ticket runner.
It is a uv workspace member, MIT-licensed, and depends only on `claude-agent-sdk` and `pydantic`.

## Public API

| Name | What it does |
| --- | --- |
| `Policy(writable, denied_commands=DEFAULT_DENIED, max_file_bytes=200_000, passthrough=frozenset({"TodoWrite"}))` | tool rules; `.decide(tool_name, tool_input, cwd, *, agent_type=None) -> Decision(allow, reason)` |
| `pre_tool_use(policy, *, audit=None)` | `PreToolUse` hook from a policy; fails closed when the policy or audit raises; returns `{}` for any other event |
| `post_tool_use(transform, *, on_error=None)` | `PostToolUse` hook; `transform(input_data)` gets the full hook input (`tool_name`, `tool_input`, `tool_response`, `tool_use_id`) and returns the replacement `tool_response` or `None` to keep it; a replacement becomes `updatedToolOutput`, which the SDK documents as replacing the tool output before it is sent to the model (for built-in tools it must match the tool's output shape, so keep a string a string and a dict a dict); a raising transform returns `{}` and calls `on_error`, so the result is never dropped; other events return `{}`; `run_ticket(..., post_tool_use=hook)` registers it |
| `run_ticket(..., extra_hooks={event: [callback, ...]})` | adds one `HookMatcher(hooks=[...])` per event after the runner's own matchers; `PreToolUse` callbacks run alongside the policy hook, and when several hooks answer, the SDK lets deny win over ask and allow |
| `deny(event_name, reason)`, `allow()` | the exact hook output shapes (`{}` allows) |
| `SessionStore(path)` | `tickets` table (`ticket_id`, `session_id`, `status`, `updated_at`, `cost_usd`): `get`, `put(ticket_id, session_id, status="open", cost_usd=0.0)`, `mark`, `close`; context manager |
| `IdempotencyStore(path)`, `once(store, key, fn)` | `ops` table; `fn` runs once per key, also across reopen |
| `RunReport`, `to_markdown(r)`, `stopped_by_from(result, budget_hit)` | the run report and its stop reason: `success`, `max_turns`, `budget`, `error`, `policy` |
| `TraceLine`, `to_trace_lines(messages)` | the M1 trace line (`n`, `role`, `text`, `tool`, `input`, `output`, `subtype`, `cost_usd`, `num_turns`, `message_id`) and a converter from SDK messages; later modules record and grade traces in this format |
| `testing.scripted_query(items, *, raise_after_error=True)` | an offline `query` replacement: yields SDK messages, raises exceptions, awaits `step(options)` callables, and raises `ResultError` after an error result the way the SDK does |
| `run_ticket(ticket_path, repo, *, policy, store, max_turns=12, max_budget_usd=0.50, model=None, agents=None, query_fn=None)` | runs one ticket with the Agent SDK and returns a `RunReport`; raises `TicketDone` for a ticket already `done`; `run_ticket_async` is the same as a coroutine |

### Policy rules

- `Read`, `Grep`, `Glob` are always allowed, and so are the `passthrough` tools (`TodoWrite` by default);
  unknown tools are denied.
- The hook passes the input's `agent_type` (set when a subagent makes the call) to `decide`; the
  default policy ignores it, and a subclass can apply a per-agent policy.
- `Write`, `Edit`, `MultiEdit`, `NotebookEdit` are allowed only when the resolved path (relative
  paths against `cwd`, `..` and symlinks resolved) is under a writable root, and the content fits
  `max_file_bytes`.
- `Bash` is denied when the command matches a denied regex, case-insensitively (by default a recursive
  `rm` in any flag spelling, `git push` also after global options such as `-C <dir>`, `curl ... | sh`,
  `sudo`) or redirects (`>`, `>>`, `&>`) to a path outside the writable roots.

### Runner behaviour

`run_ticket` builds `ClaudeAgentOptions` with `permission_mode="dontAsk"`, the six coding tools
(plus `Agent`, which is also added to the policy's `passthrough`, when `agents` is given),
the policy hook, `setting_sources=[]` and the stored session as `resume`. If a resumed run fails
before any assistant message (it raises without a result, or returns an `error_*` result), it runs
once more with a fresh session and records `resumed=False` with a note. The SDK raises `ResultError`
after yielding an error result; once a result or an assistant message has arrived, that exception is
the run's outcome, not a failed resume. The store keeps each ticket's last `total_cost_usd`; a
resumed result includes the restored spend, so the report's `cost_usd` is the result's total minus
the stored one. `stopped_by` is `budget` whenever that cost reached `max_budget_usd`, even on
`success`; a `success` result with `is_error` set (the SDK's report of a failed final request)
is `error`; a generic error after a hook denial is `policy`. `turns` is the result's `num_turns`;
without a result it is the number of distinct assistant `message_id`s. A ticket whose stored
status is `done` is not run again: `run_ticket` raises `TicketDone`. `query_fn` replaces
`claude_agent_sdk.query`, so the whole runner is testable offline with scripted messages.

`run_ticket(..., observer=fn)` calls `fn(message)` after each SDK message is stored, including
`UserMessage` tool results; every message is kept on `RunReport.messages` (left out of `to_markdown`
and `model_dump`). An observer returning a truthy value stops the run: the runner leaves the
`contextlib.aclosing` block, which ends the CLI process. If no result had arrived, the report has
`stopped_by="budget"`, `cost_usd` from the observer's `cost_usd` attribute (else 0.0), the note
`stopped by observer` and the `session_id` of the last assistant message that carried one. An
exception raised by the observer propagates out of `run_ticket`; it is never taken for a failed
resume, so it does not trigger a fresh-session retry.

### Run files

`harnesskit.testing.load_run(path)` reads a `*.jsonl` recording into `list[Timed(at_ms, message)]`
and `dump_run(path, timed)` writes it back. One JSON object per line, `t_ms` is milliseconds since
the run started:

- `{"t_ms": 0, "type": "meta", "ticket_id", "session_id"}` loads as `Timed(0, {"type": "meta", ...})`.
- `{"t_ms", "type": "assistant", "model", "message_id", "stop_reason", "usage": {"input_tokens",
  "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"}, "content": [text and
  `tool_use` blocks]}` loads as `AssistantMessage`.
- `{"t_ms", "type": "user", "content": [{"type": "tool_result", "tool_use_id", "content",
  "is_error"}]}` loads as `UserMessage`.
- `{"t_ms", "type": "result", "subtype", "num_turns", "session_id", "duration_ms",
  "duration_api_ms", "total_cost_usd", "usage", "model_usage"}` loads as `ResultMessage` with
  `is_error = subtype != "success"`.
- `{"t_ms", "type": "system", "subtype", "data"}` loads as `SystemMessage`.

A user message's `content` may also be a plain string, and assistant content may hold
`{"type": "thinking", "thinking", "signature"}` blocks (`ThinkingBlock`).

## Relation to M1

M1 learners build their own equivalents first, behind different names, in the `m1-harness-lab`
exercise (`Guard`, `guard_hook`, `TicketSessions`, `Once`, `summarise`). harnesskit is the version
later modules import, so they do not re-solve M1. Its tests are part of the root test suite:

```bash
uv run --frozen pytest fixtures/harnesskit/tests -q
```
