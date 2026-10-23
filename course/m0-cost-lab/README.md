# Inference economics cost lab

You build the pieces of a small cost-aware Claude client: a hand-written tool-use loop, streaming that ends in a final message, cache-aware prompt assembly, a cost ledger computed from usage, a batch request builder, a cost plan for a scenario, and a live check that prompt caching actually hits.

## How to run

Run every command below in a terminal at the root of your clone of this repository, after a one-time `uv sync` there; `uv run miubais doctor` lists what this machine has.

```
uv run miubais start m0-cost-lab
```

This copies `course/m0-cost-lab/starter/` to `workspace/m0-cost-lab/` at the repo root. That copy is yours: the stubs under `workspace/m0-cost-lab/src/cost_lab/` raise `NotImplementedError` until you fill them in, and the judgment stage asks for a file in the workspace root, named in its description below. The tests stay in `course/m0-cost-lab/tests/` and import your package from the workspace. `start --force` replaces the workspace with a fresh copy.

```
uv run miubais check m0-cost-lab
```

Runs the stages in order and stops at the first failure, printing its pytest output, so stage 02 waits for stage 01. `--stage <stage id>` runs one stage and `--all` keeps going past a failure. A stage whose `requires` (in `stages.yaml`) are missing on your machine is skipped, not failed. Results are kept in `~/.miubais/progress.json`; `uv run miubais reset m0-cost-lab` forgets them (`--all` for every exercise), and `start --force` does the same along with the fresh copy.

```
uv run miubais hint m0-cost-lab
```

Takes the last stage `check` saw fail, its test output and your diff against the starter, and asks the tutor on your Claude Code login for a nudge of under 90 words that is checked not to hand you the solution. If the model cannot be reached, you get a pointer to the failing test instead.

The **Run check** and **Hint** buttons on the site's exercise page do the same while `uv run miubais serve` is running, and share the progress file with the terminal.

## Stages

1. `01-tool-loop`: hand-written tool-use loop. Besides `tool_use` and `max_tokens`, it handles `refusal` (raise `RefusalError` with `stop_details.category`) and `pause_turn` (append the paused assistant content and send again).
2. `02-streaming`: streaming with a final message.
3. `03-cache-prefix`: cache-aware prompt assembly. The only breakpoint `build_request` must set is on the last static system block; nothing before it may carry `cache_control`, and one more breakpoint is allowed only on the last block of the last message. `prefix_bytes` returns the compact JSON (no spaces, keys in the order they are sent) of `model`, `tools` and `system`, so it changes whenever the bytes the cache keys on change.
4. `04-cost-ledger`: cost ledger from usage. `cost_usd` reads what the API reports when `ttl` and `batch` are left as `None`: cache writes split by TTL in `usage.cache_creation` (each priced at its own write rate; without the split, all writes count as 5-minute), the batch discount when `usage.service_tier` is `batch`, fast-mode prices from the `<model>-fast` entry when `usage.speed` is `fast` (a `ValueError` if the table has none), the `<model>-long` entry when the whole prompt is over the model's `long_context_above`, and the sum over `usage.iterations` when that list is present.
5. `05-batch-builder`: batch requests keyed by `custom_id` (a duplicate `custom_id` in results: the last one wins; the Python SDK nests an errored result as `error.error.type`, e.g. `invalid_request_error`, which is not retryable; a result line with a missing or unrecognised type is `unknown` and retryable, while an item with no result line at all counts as `expired`). A `custom_id` must match `^[a-zA-Z0-9_-]{1,64}$` (Batch processing docs), so `build_batch` raises `ValueError` for an item id that would break it.
6. `06-cost-plan`: cost plan for the scenario (judgment stage).
7. `07-live-cache-hit`: live check, cache hits on ten requests (needs an API key).

## Fixtures

Recorded API responses in `fixtures/` are synthetic until the author's `miubais record-fixtures` run (needs `ANTHROPIC_API_KEY` and the private checkout) replaces `loop_turn1`, `loop_turn2`, `cache_write`, `cache_read` and `stream_ok` with live recordings. `loop_truncated`, `stream_truncated`, `structured_ok` and `batch_results.jsonl` stay hand-made: truncation and batch failures cannot be recorded cheaply on demand, and `structured_ok` only backs the lesson 05 sample. `MANIFEST.yaml` tracks provenance per file.

## Cost plan stage

Write `COST_PLAN.md` in your workspace root. The scenario is `fixtures/scenario.yaml`, and the request log it points to is `fixtures/usage_log.jsonl`. Price six strategies with your own `cost_usd`, pick the cheapest live one, decide how the summary job runs, find the conversations whose cache never works, and explain your choices.

The test recomputes every row from the scenario with this model, per conversation:

- The prefix is the system prompt plus the tools. Turn k (1-based) sends the prefix, the user and assistant tokens of the earlier turns, and the current user turn; its output is one assistant turn. Only the prefix is ever cached, never the history.
- `gap_distribution` gives the share of conversations whose gaps between turns fall in each bucket; a conversation keeps its bucket for all its turns.
- A cached prefix is read on a turn when the gap is shorter than its TTL. Otherwise that turn writes it again at the write price of that TTL. Turn 1 always writes.
- `no-cache`: every turn pays its whole prompt at the input price.
- `cache-5m` and `cache-1h`: every conversation uses that TTL.
- `cache-by-gap`: the TTL is chosen per bucket: 5 minutes for `under_5m`, 1 hour for `5m_to_60m`, and no cache for `over_60m`.
- Live turns have a latency target (`latency_slo_seconds`), so batch is never allowed for them.
- `summary_job` runs once per conversation after it ends: its input is the prefix plus the full transcript, uncached, and its output is `output_tokens`. `summary-live` sends it synchronously; `summary-batch` sends it through the Batch API at the batch discount, which is allowed only if the deadline fits the batch window of 24 hours.
- monthly = per-conversation cost * `conversations_per_day` * `days`; a live row is the gap-weighted mean over the buckets.

The file format is parsed by the test:

```
| strategy | monthly_usd | assumptions |
| --- | ---: | --- |
| no-cache | 123456 | ... |
| cache-5m | 123456 | ... |
| cache-1h | 123456 | ... |
| cache-by-gap | 123456 | ... |
| summary-batch | 123456 | ... |
| summary-live | 123456 | ... |

chosen: <cheapest live strategy>

summary: batch|live

## Invalidator

The conversation ids from the log whose prefix is never read because something before the breakpoint changes, and what changes.

## Why

At least 80 words.
```

`monthly_usd` is a plain number (commas allowed) and each row must be within 5% of the recomputation. `chosen` must be the cheapest of the four live rows and `summary` the cheaper allowed option. The `## Invalidator` section must list exactly the affected conversation ids (written as they appear in the log, such as `conv-0001`, and no others) and say what in the request changes.
