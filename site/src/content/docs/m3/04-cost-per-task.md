---
title: Cost per task
description: Pricing every turn from its spans, reconciling the sum with the SDK's own estimate, the cache-hit ratio as the number that explains most cost differences, a budget guard backed by the SDK's cap, and what to alert on.
module: m3
order: 4
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:opentelemetry-sdk": "1.45.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/agent-sdk/cost-tracking
    title: Track cost and usage
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/agent-loop
    title: How the agent loop works
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
    title: Prompt caching
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/manage-claude/usage-cost-api
    title: Usage and Cost API
    checked: 2026-10-17
---

**Prerequisites:** [lesson 02](../02-genai-semantic-conventions/), which defines the token attributes this lesson prices.

## Why this matters for the factory

An agent factory pays per token, and the bill arrives per organisation, per day, per model. A team can act on cost per task: this ticket cost, say, 0.31 USD while its siblings cost 0.04, and here is the turn where the money went. Without that number a cost review is a guess, and the obvious guess (use a cheaper model) can miss, because model price is only one of several things that drive spend. Re-reading a large context every turn, losing the prompt cache, looping on a failing command and retrying tools all cost more than the model choice in some runs.

The same per-task number is what a budget is checked against. Stages 02 and 03 of the exercise build both: the per-task cost, and a guard that stops a run while it is still running.

## Core idea

A trace from lessons 01 and 02 already holds everything needed to price a run. Each `chat` span carries one model call's tokens in four kinds, each with its own price. Cost per span is a fixed formula over those four numbers, cost per run is the sum over its `chat` spans, and cost per task is the sum over the task's runs. The SDK computes its own estimate of the same thing and reports it on the result message, so the two can be compared, and on the recorded runs they must agree to rounding error.

Next to the total, track the cache-hit ratio, the share of the prompt that was read from the prompt cache. Cache reads cost a fraction of plain input, so two runs with the same tokens can differ in cost several times over depending on this ratio alone.

Neither number is a bill. The SDK says so about its own figure, and your span sum uses the same kind of local price table. Billing data comes from a separate API.

## Mechanics

### The formula and the four token kinds

The Messages API reports a call's prompt in three parts. Prompt caching describes `input_tokens` as the tokens "which were not read from or used to create a cache (that is, tokens after the last cache breakpoint)", and gives the whole prompt as `total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens` (Prompt caching). Output is the fourth kind. Each has its own price: the same page says "5-minute cache write tokens are 1.25 times the base input tokens price", and notes that "Cache hits and refreshes on Claude Opus 5.5 and Claude Sonnet 5.5 are priced at 0.05x the base input price" (Prompt caching). The course's price table, `fixtures/harness-runs/prices.json`, follows that: Opus 5.5 input 4.0, output 20.0, cache read 0.2 and 5-minute cache write 5.0 USD per million tokens.

Stage 02 prices a `chat` span with

```
usd = (input * p.input + output * p.output
       + cache_read * p.cache_read + cache_creation * p.cache_write_5m) / 1e6
```

where `input` is the uncached part. Lesson 02's span carries `gen_ai.usage.input_tokens` as the whole prompt by the Anthropic rule, so stage 02 subtracts the two cache attributes to get it back. The stage's test catches a cache read priced as plain input: on a cached run it moves the cost by more than 1%.

### Count each turn once

Parallel tool calls break naive sums. The SDK's cost guide says "When Claude uses tools in parallel, multiple messages share the same `id` with identical usage data. Track which IDs you've already counted and skip duplicates to avoid inflated totals" (Track cost and usage). Stage 01 already makes one `chat` span per `message_id`, so summing spans is safe. Code that sums `AssistantMessage.usage` directly, like the budget guard below, has to keep its own set of seen ids.

### Reconciling with the SDK

The result message carries `total_cost_usd`, and `model_usage` breaks it down per model with a `costUSD` field. The guide is explicit about what they are: "The `total_cost_usd` and `costUSD` fields are client-side estimates, not authoritative billing data. The SDK computes them locally from a price table bundled at build time", and they can drift "when pricing changes", "the installed SDK version does not recognize a model", or "billing rules apply that the client cannot model" (Track cost and usage). For money that matters it points elsewhere: "For authoritative billing, use the Usage and Cost API", and "Do not bill end users or trigger financial decisions from these fields" (Track cost and usage).

So reconciliation only checks two estimates against each other. Stage 02's `reconcile` compares the span sum with the root's `trace_lab.cost_usd`, copied from `total_cost_usd`. On the recorded runs the generator used the same formula and table, so the two agree to 1e-9. On live runs they will not, for three documented reasons:

- **Output tokens.** "Per-step `output_tokens` is a placeholder", the count "the API had reported at `message_start`", and the real total is on the result's `usage` or `model_usage` (Track cost and usage). Spans built from live messages under-count output, which is the most expensive kind.
- **Subagents.** The result's `usage` excludes subagent activity while `total_cost_usd` and `model_usage` include it; "the `usage` field undercounts as soon as nesting occurs" (Track cost and usage).
- **Error endings.** On `error_max_budget_usd`, "`usage` leaves out the response that crossed the budget, while `total_cost_usd` and `modelUsage` include it", and after a session crash an `error_during_execution` result may carry every cost field zeroed (Track cost and usage).

One more scoping rule matters once runs resume sessions. A resumed call "also counts the session's earlier spend", so the latest result holds the session total and "summing results double-counts the restored spend" (Track cost and usage). The harness handles that by subtracting the stored session cost when it resumes. Lesson 05 comes back to it.

The course's live run shows what this means in practice. Stage 08 ran tinyshop ticket `001-discount-rounding` on `claude-opus-5-5`, and `course/m3-trace-lab/fixtures/live_traced_run.json` records `cost_usd` 0.2074 from the SDK and `langfuse_cost_usd` 0.1179, the sum Langfuse computed from the four generations' usage with its own prices. The gap is mostly the placeholder: Langfuse priced each generation's output from the `message_start` count. For a factory the workable rule is to put on each span a cost computed from the numbers you trust (stage 04 attaches `gen_ai.usage.cost`), take the run total from the result message, and reconcile the month against the Usage and Cost API. That API returns cost "in USD with the `/v1/organizations/cost_report` endpoint", needs Admin API credentials, and its data "typically appears within 5 minutes of API request completion" (Usage and Cost API). It is too coarse to attribute a ticket and too slow to stop one, which is why the per-task number is yours to compute.

### The cache-hit ratio

Stage 02 defines `cache_hit_ratio = cache_read / (input + cache_read + cache_write)`, summed over a task's turns. It often explains why two tickets with similar work cost different amounts. A coding agent re-sends a growing prefix every turn (system prompt, tool definitions, the files read so far); when that prefix is cached, turn ten pays a twentieth of the input price for it on Opus 5.5, and when it is not, turn ten pays full price for everything. The SDK caches on its own, "You do not need to configure caching yourself" (Track cost and usage), but a cache can still be lost. The cache follows the order `tools`, `system`, `messages`, and "Changes at each level invalidate that level and all subsequent levels"; calls must come "within the cache lifetime (5 minutes by default)"; and a prompt must reach the minimum, 512 tokens on Opus 5.5: "Shorter prompts cannot be cached, even if marked with `cache_control`" (Prompt caching).

The sample prices all 40 recorded runs the way stage 02 does: per unique `message_id`, the four kinds at their own prices. It prints aggregates only, then re-prices every run with cache reads at the input price to show what caching is worth on this data. Run it with `PYTHONPATH=course/m3-trace-lab/starter/src:course/m3-trace-lab/lesson_support/src uv run --frozen python site/samples/m3/04-1.py`.

Sample: `site/samples/m3/04-1.py`.

```python
from pathlib import Path

from harnesskit.testing import load_run
from trace_lab_lessons import cost_summary, load_prices, run_cost

prices = load_prices("fixtures/harness-runs/prices.json")
paths = sorted(Path("fixtures/harness-runs/runs").glob("r*.jsonl"))
runs = [run_cost(load_run(path), prices) for path in paths]
summary = cost_summary(runs)

wrong = {model: dict(p) for model, p in prices.items() if isinstance(p, dict)}
for price in wrong.values():
    price["cache_read"] = price["input"]
mispriced = sum(run_cost(load_run(path), wrong).usd for path in paths)

rows = [
    ("runs / tickets", f"{summary['runs']} / {summary['tickets']}"),
    ("total cost, USD", f"{summary['total_usd']:.4f}"),
    ("mean cache-hit ratio", f"{summary['mean_ticket_cache_hit']:.3f}"),
    ("costliest quartile share", f"{summary['top_quartile_run_share']:.1%}"),
    ("runs with a result", f"{summary['runs_with_result']}"),
    ("max |delta| below 1e-9", f"{summary['max_reconcile_delta'] < 1e-9}"),
    ("cache read as input, USD", f"{mispriced:.4f}"),
]
for label, value in rows:
    print(f"{label:<26}{value:>8}")
```

Output, run on 2026-10-17:

```
runs / tickets             40 / 10
total cost, USD             4.8683
mean cache-hit ratio         0.664
costliest quartile share     43.1%
runs with a result              38
max |delta| below 1e-9        True
cache read as input, USD   13.6050
```

The 40 runs cost 4.87 USD in total, and the costliest quarter of them (ten runs) took 43% of that, so spend is concentrated and a review should start there rather than at the average. The 38 runs that ended with a result reconcile with the SDK's figure to rounding error; the other two were cut off and have nothing to reconcile against. The mean cache-hit ratio, 0.664 (mean of the ten per-ticket ratios, not a ratio over the pooled tokens), weights every ticket equally, so one heavily cached ticket counts no more than one uncached ticket. Without the cache discount the same tokens would cost 13.61 USD, almost three times as much, which is why a falling cache-hit ratio is the first thing to check when a ticket's cost jumps. Which tickets sit in that costly quarter and why is stage 07's question, so the sample does not list them.

### Budgets: a guard and a backstop

Stage 03's `BudgetGuard` is a harness observer. It sees every message, prices each new `message_id` with the same formula, and returns `True` on the first message that takes its estimate strictly above the limit; the runner then leaves the SDK iterator and the report says `stopped_by="budget"`. Because live per-step output counts are placeholders, that estimate is a floor: input and cache tokens are accurate, output is not. A run the guard stops has also produced no result message, so the report's cost is the guard's floor, not the SDK's estimate.

That is why `run_with_budget` also passes the limit as `max_budget_usd`. The SDK option will "Stop the query when the client-side cost estimate reaches this USD value. The estimate can pass this value, so leave headroom" (Agent SDK reference - Python). It checks spend "after model responses arrive", and "The response that reaches the cap still completes and counts toward `total_cost_usd`", so spend "can therefore pass the cap by up to the cost of that one response" (How the agent loop works). It also covers subagents: "their spend counts toward the total" (How the agent loop works). Each control covers a gap in the other. The guard acts mid-stream on your own price table and can use a lower internal threshold if you pass one (a recommendation: `run_with_budget` passes the same limit to both); the SDK cap uses real output counts and sees subagent spend. `max_budget_usd` "counts only the call's own spend: totals restored from a resumed session don't count against it" (Track cost and usage).

### What to alert on

Per task, alert on events, not on averages: any `stopped_by="budget"`; a run that costs more than a multiple of the median for its ticket class; a cache-hit ratio that drops well below the class's usual value; and a reconcile delta on a run where the inputs should agree. Per day, alert on total spend against a daily budget, on the count of budget stops, and on a drop in the day's mean cache-hit ratio, which often means a prompt or tool definition changed and broke the cached prefix for every ticket at once. Reconcile the day's span sum against the Usage and Cost API once its data has arrived; a growing gap means your price table is stale.

## Common pitfalls

- **Pricing cache reads as input.** On the recorded runs this nearly triples the total.
- **Summing every `AssistantMessage`.** Parallel tool calls repeat one id with identical usage. Count each id once.
- **Taking output from per-step usage on live runs.** It is the `message_start` placeholder. Read output from the result.
- **Summing results across resumed calls.** Each one already includes the session's earlier spend.
- **Treating `total_cost_usd` as the bill.** It is a client-side estimate. Bill from the Usage and Cost API.
- **A guard that checks only the result message.** By then the money is spent. Check every message.

## What interviewers ask

**How do you compute the cost of one agent task?**
Price each model call from its four token kinds (uncached input, output, cache read, cache write) at their own prices, count each message id once, sum over the run's calls and over the task's runs. Take the output total from the result message on live runs, because per-step output is a placeholder.

**Your span-based cost and the SDK's `total_cost_usd` disagree. Which is right?**
Neither is the bill; both are local estimates. Check the known gaps first: placeholder output, subagent tokens missing from `usage`, the crossing response on a budget stop, a crash zeroing fields. For billing, reconcile against the Usage and Cost API.

**Why does the cache-hit ratio matter so much?**
A coding agent re-sends a growing prefix every turn. Cached, that prefix costs 0.05x to 0.1x of input; uncached, full price. On the course's 40 runs, pricing cache reads as input moves the total from 4.87 to 13.61 USD.

**Why have both a client-side budget guard and `max_budget_usd`?**
The guard stops mid-stream on your own prices but its estimate is a floor on live runs. The SDK cap uses the real counts after each response and includes subagents, but lets the crossing response complete. Together they bound the run from both sides.

**What would you alert on for a factory running hundreds of tickets a day?**
Per task: budget stops, cost outliers against the ticket class, cache-hit drops. Per day: total against budget, the count of budget stops, the mean cache-hit ratio, and drift against the billing API.

## Sources

- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), Claude Agent SDK docs, checked 2026-10-17
- [How the agent loop works](https://code.claude.com/docs/en/agent-sdk/agent-loop), section Budget headroom, Claude Agent SDK docs, checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), `ClaudeAgentOptions.max_budget_usd`, checked 2026-10-17
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), Claude API docs, checked 2026-10-17
- [Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api), Claude API docs, checked 2026-10-17
- Course code and records (repository files, not web sources): stages 02 and 03 in `course/m3-trace-lab/README.md`; the lesson helpers in `course/m3-trace-lab/lesson_support/src/trace_lab_lessons/`; the price table `fixtures/harness-runs/prices.json`; the recorded runs and their README in `fixtures/harness-runs/`; the live record `course/m3-trace-lab/fixtures/live_traced_run.json`
