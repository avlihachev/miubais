---
title: "Cost levers: batch, effort, budgets, model choice"
description: Price agent work per completed task, route waiting work through the Batch API, set effort and task budgets deliberately, and know when a stronger model at low effort beats a cheaper one.
module: m0
order: 4
verified_on: 2026-10-17
executed: local
pins:
  "pypi:anthropic": "1.15.0"
  "model:default": claude-opus-5-5
sources:
  - url: https://platform.claude.com/docs/en/build-with-claude/batch-processing
    title: Batch processing
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/effort
    title: Effort
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost
    title: Steering thinking
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
    title: Thinking overview
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/task-budgets
    title: Task budgets
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/fast-mode
    title: Fast mode
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence
    title: Optimizing for cost and intelligence
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/about-claude/pricing
    title: Claude pricing
    checked: 2026-10-17
---

**Prerequisites:** [lesson 03](../03-prompt-caching/), because every lever here is priced on top of the cache.

## Why this matters for the factory

Lessons 01 to 03 explained where tokens go and how caching stops you paying twice for the same prefix. This lesson covers the remaining levers that change what a unit of agent work costs: when it runs (synchronous or batch), how hard the model works on it (effort, thinking, task budgets), which model does it, and how fast you need the output (fast mode). In a factory the unit that matters is a completed task: a merged patch, a triaged ticket, a classified document. A request that is cheap but fails, and then gets retried or escalated to a person, costs more than a request that is expensive and succeeds.

The levers fall into two groups, and Anthropic's cost guide draws the same line (Optimizing for cost and intelligence). Caching and batching cut spend without touching quality. Effort, model tier and budgets trade quality for cost along a curve. Use the first group everywhere it applies before you touch the second, and when you do touch the second, measure on your own tasks, because the published numbers are directional.

## Core idea

Write the cost of a task as a product of three factors:

```
 cost per completed task = (tokens per attempt x price per token) / success rate
```

Tokens per attempt move with effort, thinking, the task budget and context hygiene; the price per token with model tier, batch (0.5x), fast mode (2x) and the cache (lesson 03); the success rate with model tier, effort, and a verifier with re-runs.

Every lever moves at least one factor, and several move two in opposite directions. Lower effort cuts tokens per attempt and can lower the success rate. A cheaper model cuts the price per token and can raise tokens per attempt, because a weaker model may need more turns, and lower the success rate. Batch halves the price per token and changes nothing else, except that results arrive any time within 24 hours. Fast mode doubles the price per token on Opus 5.5 to buy output speed. A per-token comparison sees only the middle factor, which is why it misleads.

On a 478-problem SWE-bench Pro subset, run in September 2026 and priced at list prices with the 5-minute cache, Sonnet 5.5 at its default `high` effort solved 87.6% of tasks for $0.11 per solved task, and Opus 5.5 at `low` effort solved 87.4% for $0.12. Each of Opus 5.5's token prices is twice Sonnet 5.5's ($4 / $20 against $2 / $10 per MTok, Claude pricing), yet the cost per solved task differed by about $0.01 per task, because the stronger model did the same work in fewer tokens. On the same subset Opus 5.5 at its default `medium` solved 92.8% for $0.22 per solved task (Optimizing for cost and intelligence). The guide is explicit that the ranking flips by workload and that no price list tells you which way.

## Mechanics

### Batch: half price for work no one is waiting on

The Message Batches API takes 50% off all token usage, input and output (Batch processing; Claude pricing); cache hits inside a batch are best-effort, per the docs. On Opus 5.5 that is $2 input and $10 output per MTok. The limits, all from the Batch processing page: a batch holds up to 100,000 requests or 256 MB, whichever comes first; most batches finish within 1 hour; a batch expires if processing has not finished within 24 hours; results stay downloadable for 29 days after creation. `stream: true`, `speed` (fast mode) and `max_tokens: 0` are rejected inside a batch.

Results come back as JSONL in any order, so you key every request by `custom_id` and join on it. Each result has one of four types: `succeeded` (with the message), `errored`, `canceled` and `expired`. You are not billed for the last three. An `errored` result carries the standard error shape in `result.error`; when `result.error.error.type` is `invalid_request_error` the request must be fixed before you resend it, while other errors can be retried as they are. `expired` means the 24-hour window closed before the request ran, so resubmit it in a new batch.

The sample below uses `batch_requests` and `join_batch` from `course/m0-cost-lab/lesson_support/` (helpers written for these lessons, not the exercise solution). It builds six requests, joins the hand-made `fixtures/batch_results.jsonl` (six shuffled lines: four succeeded, one errored, one expired) and prices the billed results at standard and batch rates. The sample assumes 1,200 input and 300 output tokens per succeeded request. The fixture nests the error as the live Python SDK does, and the join reads `result.error.error.type`, so the `retryable=False` line for item 2 comes from the nested shape. Run it from the repository root with `PYTHONPATH=course/m0-cost-lab/starter/src:course/m0-cost-lab/lesson_support/src uv run --frozen python site/samples/m0/04-1.py`.

Sample: `site/samples/m0/04-1.py`.

```python
import json
from pathlib import Path

from cost_lab_lessons import batch_requests, join_batch

FIXTURES = Path("course/m0-cost-lab/fixtures")
MODEL = "claude-opus-5-5"
USD_PER_MTOK = {"input": 4.00, "output": 20.00}
BATCH_DISCOUNT = 0.5
ASSUMED_INPUT, ASSUMED_OUTPUT = 1200, 300

prompts = {str(n): f"Summarise changelog entry {n} in two sentences." for n in range(1, 7)}
requests = batch_requests(prompts, model=MODEL, max_tokens=16000)
print("first request:", json.dumps(requests[0]))

lines = (FIXTURES / "batch_results.jsonl").read_text().splitlines()
outcomes = join_batch(list(prompts), [json.loads(line) for line in lines])
for key, outcome in outcomes.items():
    print(f"item {key}: {outcome.kind:<9} retryable={outcome.retryable} text={outcome.text!r}")

billed = [key for key, o in outcomes.items() if o.kind == "succeeded"]
per_request = (
    ASSUMED_INPUT * USD_PER_MTOK["input"] + ASSUMED_OUTPUT * USD_PER_MTOK["output"]
) / 1e6
standard = len(billed) * per_request
batched = standard * BATCH_DISCOUNT
print(f"billed {len(billed)} of {len(prompts)}: standard ${standard:.4f}, batch ${batched:.4f}")
print("resubmit:", [key for key, o in outcomes.items() if o.retryable])
```

Output, run on 2026-10-17:

```
first request: {"custom_id": "item-1", "params": {"model": "claude-opus-5-5", "max_tokens": 16000, "messages": [{"role": "user", "content": "Summarise changelog entry 1 in two sentences."}]}}
item 1: succeeded retryable=False text='answer one'
item 2: errored   retryable=False text=None
item 3: succeeded retryable=False text='answer three'
item 4: succeeded retryable=False text='answer four'
item 5: expired   retryable=True text=None
item 6: succeeded retryable=False text='answer six'
billed 4 of 6: standard $0.0432, batch $0.0216
resubmit: ['5']
```

The join comes back in item order although the file was shuffled, the errored request is marked for a fix rather than a blind retry, and only the expired one is queued for resubmission. Each succeeded request costs $0.0108 at standard rates (1,200 x $4 + 300 x $20 per MTok) and $0.0054 in a batch.

Batch is for work no one is waiting on. A live chat turn with a latency target of a few seconds can never go there, however attractive the discount; the end-of-conversation summary, the nightly tagging run and the evaluation suite can. Split a workload into those two kinds before you price it, and price the batch part with its own cache assumptions: a batch can take up to 24 hours, so a 5-minute entry written by the interactive path is usually gone by then, and the Batch processing page recommends the 1-hour TTL for batches that share context.

### Pricing a plan per conversation

A cost plan for a chat workload is a per-conversation formula multiplied by volume. Take a toy assistant: 2,000 conversations a day for 30 days, four turns each, a 6,000-token static prefix (system plus tools), 100-token user turns and 300-token replies on Opus 5.5. For n turns, prefix P, user turn u and reply a:

- Turn k sends the prefix plus the history so far, (k - 1)(u + a) + u uncached tokens, and produces a output tokens. Summed over the turns, the history is n u + (u + a) n (n - 1) / 2 tokens; here 2,800.
- No cache: n P + history at the input price, plus n a at the output price.
- A cache that survives every gap: one write of P at the write price of its TTL, n - 1 reads of P at the read price, the history at the input price, the same output.
- A cache that expires on every gap: n writes of P and no reads, which is worse than not caching.
- When only a share of conversations has long gaps, the plan is the share-weighted mean of the cases, and the TTL can be chosen per class of conversation when you can tell them apart (a chat widget against an email-style follow-up).

The sample computes each case. It needs no fixture and no course code; run it with `uv run --frozen python site/samples/m0/04-2.py`.

Sample: `site/samples/m0/04-2.py`.

```python
USD_PER_MTOK = {
    "input": 4.00,
    "output": 20.00,
    "cache_read": 0.20,
    "write_5m": 5.00,
    "write_1h": 8.00,
}
CONVERSATIONS = 2_000 * 30
TURNS, PREFIX, USER, ASSISTANT = 4, 6_000, 100, 300
LONG_GAP_SHARE = 0.4

history = sum((k - 1) * (USER + ASSISTANT) + USER for k in range(1, TURNS + 1))
fixed = (history * USD_PER_MTOK["input"] + TURNS * ASSISTANT * USD_PER_MTOK["output"]) / 1e6


def prefix_usd(writes: int, reads: int, write_price: float) -> float:
    return (writes * write_price + reads * USD_PER_MTOK["cache_read"]) * PREFIX / 1e6


no_cache = TURNS * PREFIX * USD_PER_MTOK["input"] / 1e6 + fixed
hit_5m = prefix_usd(1, TURNS - 1, USD_PER_MTOK["write_5m"]) + fixed
miss_5m = prefix_usd(TURNS, 0, USD_PER_MTOK["write_5m"]) + fixed
hit_1h = prefix_usd(1, TURNS - 1, USD_PER_MTOK["write_1h"]) + fixed

print(f"history input per conversation: {history} tokens")
for name, usd in [
    ("no cache", no_cache),
    ("5m, every gap short", hit_5m),
    ("5m, every gap long", miss_5m),
    ("1h, every gap under 1h", hit_1h),
    ("5m, 40% long gaps", (1 - LONG_GAP_SHARE) * hit_5m + LONG_GAP_SHARE * miss_5m),
    ("5m or 1h by gap", (1 - LONG_GAP_SHARE) * hit_5m + LONG_GAP_SHARE * hit_1h),
]:
    print(f"{name:<24} ${usd:.5f}/conversation  ${usd * CONVERSATIONS:,.0f}/month")
```

Output, run on 2026-10-17:

```
history input per conversation: 2800 tokens
no cache                 $0.13120/conversation  $7,872/month
5m, every gap short      $0.06880/conversation  $4,128/month
5m, every gap long       $0.15520/conversation  $9,312/month
1h, every gap under 1h   $0.08680/conversation  $5,208/month
5m, 40% long gaps        $0.10336/conversation  $6,202/month
5m or 1h by gap          $0.07600/conversation  $4,560/month
```

With short gaps everywhere, the 5-minute cache roughly halves the bill. When 40% of the conversations wait longer than five minutes between turns, a single 5-minute TTL loses most of that saving, because those conversations re-write the prefix on every turn, and choosing the TTL by gap class recovers it. The exercise's stage `06-cost-plan` uses a different scenario with its own numbers, a gap distribution, a summary job and a request log, and asks you to price it with your own `cost_usd`; nothing on this page is its answer.

### Effort and thinking

`output_config.effort` takes `low`, `medium`, `high`, `xhigh` or `max`. It shapes every output token: thinking, text and tool calls, and lower effort also means fewer and terser tool calls (Effort). Opus 5.5 and Haiku 5.5 default to `medium`; most other models, Sonnet 5.5 included, default to `high`. Sending the default explicitly is identical to omitting it. Effort is a behavioural signal, not a token cap.

On Opus 5.5 adaptive thinking is always on and cannot be disabled: `thinking: {"type": "disabled"}` returns 400 at every effort level, so effort is the main control for how much the model reasons. Sonnet 5.5 cannot switch thinking off either: the Effort page says to send `thinking: {"type": "between_tools"}` instead of `disabled`, which is its lowest setting, drops up-front thinking at `low`, `medium` and `high`, and returns 400 at `xhigh` and `max`. Manual `thinking: {"type": "enabled"}` with `budget_tokens` returns 400 on both models (Thinking overview). Thinking tokens are billed as output tokens at the full rate even when the display is summarised or omitted, and `usage.output_tokens_details.thinking_tokens` tells you how many there were (Steering thinking).

Effort is part of the rendered prompt. Changing the top-level value between requests invalidates cache breakpoints in the messages; the Steering thinking page shows a third request at `low` after two at the default re-writing 3,546 cached tokens. To vary effort turn by turn without losing the cache, Fable 5.1, Mythos 5.1, Opus 5.5, Opus 5, Sonnet 5.5 and Haiku 5.5 accept a per-message `output_config` on a mid-conversation system message on the Claude API, behind the `mid-conversation-output-config-2026-07-01` beta; on Amazon Bedrock only Fable 5.1, Mythos 5.1 and Opus 5.5 do. It is not available on Sonnet 5.5 with `thinking: {"type": "between_tools"}` or on Haiku 5.5 with thinking disabled, where a per-message effort that differs from the level in effect returns 400 (Effort).

When outputs are checkable, a re-run policy can beat any single effort level. The cost guide computed, from the same Opus 5.5 SWE-bench Pro runs, that running everything at `low` and re-running the failures (13% of tasks) at `high` solved about 97% of tasks for about $0.17 per task, against 95.3% for $0.29 with everything at `high` (Optimizing for cost and intelligence). It needs a trustworthy failure signal, such as tests, and it doubles the latency of every first-pass failure.

### Task budgets

`max_tokens` caps one request. An agent turn spans many requests, so it does not bound what the turn spends. Task budgets fill that gap: with the `task-budgets-2026-03-13` beta you set `output_config.task_budget = {"type": "tokens", "total": N}`, and the model sees a server-side countdown covering thinking, tool calls, tool results and output across the whole loop, and paces itself to finish gracefully (Task budgets). The minimum `total` is 20,000; smaller values return 400. The budget is advisory: the model may overrun to finish an action, and `max_tokens` stays the hard per-request limit. The countdown is not returned in `usage`, so track spend from your own ledger. A budget that is clearly too small for the task can make the model decline or scope down, and changing the value mid-task invalidates the cache like any other rendered setting.

The documented examples stream, because a large `max_tokens` needs streaming in the SDK. This request goes through the recorded transport with the `stream_ok` fixture, so it runs offline and shows what reaches the wire; run it with `PYTHONPATH=course/m0-cost-lab/starter/src:course/m0-cost-lab/lesson_support/src uv run --frozen python site/samples/m0/04-3.py`:

Sample: `site/samples/m0/04-3.py`.

```python
import json
from pathlib import Path

from cost_lab.transport import make_client

client, transport = make_client(Path("course/m0-cost-lab/fixtures"), ["stream_ok"])
with client.beta.messages.stream(
    model="claude-opus-5-5",
    max_tokens=64000,
    betas=["task-budgets-2026-03-13"],
    output_config={"effort": "low", "task_budget": {"type": "tokens", "total": 40000}},
    messages=[
        {
            "role": "user",
            "content": "Triage the failing test in tests/test_api.py and propose a fix.",
        }
    ],
) as stream:
    final = stream.get_final_message()

sent = transport.requests[0].body
print("sent:", json.dumps({k: sent[k] for k in ("model", "max_tokens", "output_config", "stream")}))
print(
    "stop_reason:", final.stop_reason, "usage:", final.usage.input_tokens, final.usage.output_tokens
)
```

Output, run on 2026-10-17 (the reply and its usage are the synthetic fixture):

```
sent: {"model": "claude-opus-5-5", "max_tokens": 64000, "output_config": {"effort": "low", "task_budget": {"type": "tokens", "total": 40000}}, "stream": true}
stop_reason: end_turn usage: 40 9
```

### Fast mode: paying more for speed

Fast mode runs the same model with a faster inference configuration: up to 2.5x higher output tokens per second, with no gain in time to first token (Fast mode). You opt in with `speed: "fast"`, and `usage.speed` reports which speed you got. On Opus 5.5 it costs $8 input and $40 output per MTok, twice the standard price, and cache multipliers apply on top. The `fast-mode-2026-02-01` beta header was required during the research preview; Opus 5.5 no longer needs it, though requests that still send it keep working, while Opus 5 and Opus 4.8 still do. Fast and standard requests do not share cached prefixes, so falling back from fast to standard on a 429 costs a cache miss, and fast mode is rejected inside a batch. Use it when a person is watching a long generation stream; unattended work gains nothing from it.

## Common pitfalls

- **Comparing models per token.** A cheaper model that needs more turns, or fails more often, costs more per completed task. Price candidates on cost per solved task over your hardest tenth of tasks, as the cost guide advises, and include the stronger model at low effort.
- **Batching with a 5-minute cache.** Batched requests often run after the entry expires and pay the write premium again. Use `"ttl": "1h"` for shared batch context, and model it in the plan.
- **Retrying every errored batch result.** `invalid_request_error` will fail again. Branch on `result.error.error.type`, fix and resend invalid requests, retry the rest, and resubmit `expired` items in a new batch.
- **Joining batch results by position.** Results arrive in any order. Key by `custom_id` and treat a missing id as expired.
- **Trying to switch thinking off on Opus 5.5 or Sonnet 5.5.** `thinking: {"type": "disabled"}` returns 400 on Opus 5.5, and Sonnet 5.5's lowest documented setting is `between_tools`. Lower effort on Opus 5.5, or use `between_tools` on Sonnet 5.5 at `high` or below.
- **Switching effort per turn on the top-level field.** Each change re-writes the cached history. Pick one level per session, or use the per-message beta.

## What interviewers ask

**Why is cost per completed task the right metric, not cost per request?**
Because failed attempts still bill their tokens, then the retry, then whatever the failure costs downstream. A model or effort level with a lower per-request price can lose once the success rate is in the denominator, as the SWE-bench Pro numbers for Sonnet 5.5 at `high` and Opus 5.5 at `low` show.

**What work belongs in the Batch API and what does not?**
Anything no one is waiting on: evaluations, backfills, scheduled triage, offline classification, at 50% off with results within 24 hours. Interactive turns, streamed output and fast mode do not belong there, and batched work that shares context should use the 1-hour cache TTL.

**How do you bound the cost of a long agent turn?**
`max_tokens` bounds each request, a task budget (beta, minimum 20,000 tokens) gives the model an advisory target for the whole loop, and your own ledger plus a workspace spend limit are the hard stops. Effort sets how much reasoning each step gets.

**When would you choose Opus 5.5 at low effort over Sonnet 5.5 at high?**
When your evals show it solves the same share of tasks for a similar cost per solved task, as on Anthropic's SWE-bench Pro subset (87.4% at $0.12 against 87.6% at $0.11), and you value its headroom: raising its effort later buys quality without a model migration. The opposite workload exists too, so measure.

**What does fast mode change and what does it cost?**
It raises output tokens per second by up to 2.5x on the same model, without improving time to first token, at twice the standard price on Opus 5.5 ($8 / $40 per MTok). It does not share a cache with standard-speed requests and cannot be batched.

## Sources

- [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing), checked 2026-10-17
- [Effort](https://platform.claude.com/docs/en/build-with-claude/effort), checked 2026-10-17
- [Steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost), checked 2026-10-17
- [Thinking overview](https://platform.claude.com/docs/en/build-with-claude/extended-thinking), checked 2026-10-17
- [Task budgets](https://platform.claude.com/docs/en/build-with-claude/task-budgets), checked 2026-10-17
- [Fast mode](https://platform.claude.com/docs/en/build-with-claude/fast-mode), checked 2026-10-17
- [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence), checked 2026-10-17
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-10-17
- Course code (repository files, not web sources): the lesson helpers in `course/m0-cost-lab/lesson_support/src/cost_lab_lessons/` and the recorded transport in `course/m0-cost-lab/starter/src/cost_lab/transport.py`
