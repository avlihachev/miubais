# Enforced harness lab

You build your own enforced harness around the Claude Agent SDK: a policy engine, a hook adapter that enforces it, durable ticket sessions, idempotent tools, turn and budget caps, a reviewer subagent with a schema-bound verdict, a failure taxonomy, and one live run on a small repo.

## How to run

Run every command below in a terminal at the root of your clone of this repository, after a one-time `uv sync` there; `uv run miubais doctor` lists what this machine has.

```
uv run miubais start m1-harness-lab
```

This copies `course/m1-harness-lab/starter/` to `workspace/m1-harness-lab/` at the repo root. That copy is yours: the stubs under `workspace/m1-harness-lab/src/harness_lab/` raise `NotImplementedError` until you fill them in, and the judgment stage asks for a file in the workspace root, named in its description below. The tests stay in `course/m1-harness-lab/tests/` and import your package from the workspace. `start --force` replaces the workspace with a fresh copy.

```
uv run miubais check m1-harness-lab
```

Runs the stages in order and stops at the first failure, printing its pytest output, so stage 02 waits for stage 01. `--stage <stage id>` runs one stage and `--all` keeps going past a failure. A stage whose `requires` (in `stages.yaml`) are missing on your machine is skipped, not failed. Results are kept in `~/.miubais/progress.json`; `uv run miubais reset m1-harness-lab` forgets them (`--all` for every exercise), and `start --force` does the same along with the fresh copy.

```
uv run miubais hint m1-harness-lab
```

Takes the last stage `check` saw fail, its test output and your diff against the starter, and asks the tutor on your Claude Code login for a nudge of under 90 words that is checked not to hand you the solution. If the model cannot be reached, you get a pointer to the failing test instead.

The **Run check** and **Hint** buttons on the site's exercise page do the same while `uv run miubais serve` is running, and share the progress file with the terminal.

## Stages

1. `01-policy-engine`: `Guard` decides whether a tool call is allowed under writable roots and blocked command patterns, which match case-insensitively.
2. `02-hook-adapter`: `guard_hook` turns a `Guard` into a `PreToolUse` hook that denies on any doubt, including its own errors. It answers `PreToolUse` events only and returns `{}` for any other event, whose output shapes differ.
3. `03-session-store`: `TicketSessions` persists session ids and each ticket's last total cost, adding the `cost_usd` column to a `sessions` table created before it existed; `resume_or_fresh` falls back to a fresh session when a resume fails before any output. The SDK raises `ResultError` after it yields an error result, so once a `ResultMessage` has arrived that exception is the run's outcome, not a failure to resume.
4. `04-idempotent-tools`: `Once` makes a side effect run once per key, across restarts.
5. `05-caps-and-report`: `Caps` and `summarise` turn a message stream into a `Summary` that says why the run stopped. `turns` is the result's `num_turns` (without a result, the number of distinct assistant `message_id`s); `max_turns` comes from the result's subtype only; a result with subtype `success` but `is_error` set stops as `error`. On a resumed run, `previous_cost_usd` is subtracted from the result's total before it is compared with the cap.
6. `06-subagent-verdict`: a read-only reviewer subagent whose verdict is validated against a schema.
7. `07-failure-taxonomy`: classify harness failures from recorded traces (judgment stage).
8. `08-live-ticket`: run your harness on a `tinyshop` ticket against the real Agent SDK.

Stages 03 and 04 each keep one SQLite table: `sessions(ticket_id TEXT PRIMARY KEY, session_id TEXT, status TEXT, updated_at TEXT, cost_usd REAL)` and `ops(key TEXT PRIMARY KEY, result TEXT, at TEXT)`.

## Relation to harnesskit

The repository's top-level `fixtures/harnesskit` is the course's shared library, with the same ideas under different names. Build your own `harness_lab` first; later modules use `harnesskit`.

## The live stage

Stage 08 runs your `run_ticket` on ticket `001-discount-rounding` against the real Agent SDK on your Claude Code login (model `claude-opus-5-5`, caps 12 turns and 0.75 USD; a run during the build took 8 assistant messages and about 0.21 USD; it is not committed as a record). It is skipped when `claude auth status` reports no login. Once it has passed, `miubais check` does not spend on it again and shows `passed (cached live)`; run it again with `--stage 08-live-ticket` or `--live`. Set `MIUBAIS_SKIP_LIVE=1` to skip only the live run inside the stage while the offline checks of the runner's options still run; the stage is then reported as `skipped (MIUBAIS_SKIP_LIVE=1)` when those checks pass, and that is never recorded as a pass. `miubais selftest` grades offline by default and reports `08-live-ticket ok (offline)`: it sets the variable, deselects tests marked `@pytest.mark.live`, and loads the `miubais.offline_guard` pytest plugin, which makes `claude_agent_sdk.query`, `ClaudeSDKClient.connect` and any `anthropic` client without an injected `http_client` raise `live call under offline grading`. `scripts/verify.sh` sets the variable too.

## Fixtures

`fixtures/events/`, `fixtures/traces/` and `fixtures/verdicts/` hold hook events, recorded run traces and reviewer verdicts used by the stages. The live stage copies the top-level `fixtures/tinyshop`, a tiny shop library with three planted bugs, one per ticket in `fixtures/tinyshop/tickets/`.

## Failure taxonomy stage

`fixtures/traces/t01.jsonl` to `t12.jsonl` are excerpts of harness runs on `tinyshop` tickets. Each line is one JSON object with `n` (the line number), `role` (`user`, `assistant`, `tool` or `result`) and, depending on the role, `text`, `tool` and `input` (a tool call), `output` (a tool result), or `subtype`, `cost_usd` and `num_turns` (the final result). Each trace shows exactly one category:

- `loop`: the agent repeats the same tool calls, or the same pair of edits, without a new outcome. Progress stops while turns and cost keep going up until a cap ends the run.
- `scope-creep`: the agent knowingly changes things the ticket did not ask for. The ticket may well be fixed, but the diff carries refactors, new files or edits to unrelated modules.
- `silent-skip`: the agent leaves out a required step, usually the acceptance check, and reports success as if it had been done. The trace shows the check missing, erroring or running no tests, while the final message claims it passed.
- `policy-denied-retry`: the policy denies a call and the agent keeps pursuing the same denied goal through other tools, paths or phrasings. A single denial followed by a different, allowed approach is not this category.
- `tool-result-poisoning`: text inside a tool result (a file, a log, a command's output) gives instructions and the agent follows them as if they came from the user. The tell is the agent citing repository content as the reason for a change the ticket never asked for.
- `budget-blowout`: the run spends its budget on work out of proportion to the ticket, such as reading large files or dumping huge outputs. It ends on the budget cap, often with the actual fix small or still unverified.
- `context-loss`: the agent loses a fact or the goal it had earlier, typically after compaction, and acts on a wrong or stale picture. It then works confidently on the wrong thing, such as another ticket.
- `success`: the run did what the ticket asked and verified it. Some successful traces look suspicious at first glance (a denial, a failed first attempt) and are still fine.

Write `FAILURES.md` in your workspace root with a table of 12 rows and a `## Fixes` section:

```
| trace | category | evidence |
| --- | --- | --- |
| t01 | <category> | <at least 8 words citing up to four lines of that trace as line N> |

## Fixes

**<category>**: <one paragraph of at least 40 words on how the harness should prevent or catch it>
```

Every row needs one of the categories above. Evidence cites at most four lines as `line N`, every cited line must exist in that trace, and at least one must be a line that shows the category; the lines that merely set the scene do not count. For a few traces, where one specific tool's calls are the tell, naming that tool is accepted instead of a line. `## Fixes` has one paragraph per failure category you found (not `success`), each starting with the category name. The stage passes with at least 10 of 12 classifications matching the answer key.

The answer key for this judgment stage lives under `tests/`; reading it defeats the exercise and is left to your honesty.
