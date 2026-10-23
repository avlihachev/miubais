---
title: "Interview angle: inference economics"
description: The questions an interviewer asks about LLM cost and latency, a system-design prompt for a high-volume support assistant, and what a short take-home on this topic looks like.
module: m0
order: 7
freshness: skip
---

**Prerequisites:** lessons 01 to 06 of [M0](../), which this page assumes you have read.

This page collects what lessons 01 to 06 prepare you to answer out loud. Numbers are Opus 5.5 list prices from the pricing page as checked in those lessons: $4 per MTok input, $20 output, $0.20 cache read, $5 five-minute write, $8 one-hour write.

## What they ask

**1. What is the difference between time to first token and tokens per second?**
Time to first token is dominated by prefill, which processes the whole prompt in parallel and is compute-bound, so it grows with prompt length. Tokens per second is the decode rate, which is memory-bandwidth-bound, and it also falls as the context grows, because every decode step reads the whole KV cache of the sequence; a long answer is slow even when the first token was fast, and slower still on a long prompt.

**2. Why does output cost five times input?**
Decode produces one token per forward pass and reads the weights and the whole KV cache every time, while prefill amortises that cost over thousands of tokens at once. Anthropic does not publish its cost model, so say that the 5x ratio is consistent with that hardware story rather than a disclosed formula; either way, cost a workload against $20 versus $4 on Opus 5.5.

**3. When does a 5-minute cache pay off, and when a 1-hour one?**
A 5-minute write costs 1.25x input, a read costs 0.05x, so one read already beats not caching. A 1-hour write costs 2x, so it needs two reads, and it wins when requests with the same prefix arrive more than five minutes apart but at least twice within the hour.

**4. What silently invalidates a cache, and how do you prove you got a hit?**
Anything that changes bytes before the breakpoint: a timestamp in the system prompt, unsorted tool keys, a changed tool list, a different model. Read `usage.cache_read_input_tokens` and `cache_creation_input_tokens` on the second request, and log the hit ratio per call.

**5. When do you use the Batch API?**
When nobody is waiting: evals, backfills, nightly classification, document enrichment. It takes 50% off token usage with results typically within an hour and at most 24, in any order, so you key every request by `custom_id` and handle errored and expired results explicitly.

**6. Effort level or model choice for cost?**
Decide on cost per solved task, not per token. In Anthropic's SWE-bench Pro measurement (Optimizing for cost and intelligence, via lesson 04), Opus 5.5 at low effort matched Sonnet 5.5 at high for about a cent more per solved task ($0.12 against $0.11), so measure success rate and tokens per attempt on your workload before you pick.

**7. Strict tools or structured outputs?**
Structured outputs constrain the final response to a JSON schema, so use them when the answer itself is data. Strict tools guarantee that tool inputs match their schema, so use them when the model calls your functions; both remove parsing retries, and neither removes the need to validate business rules.

**8. Compaction or context editing?**
Compaction summarises everything before a point, which is lossy but general, and suits long conversations that outgrow the window. Context editing clears old tool results by rule and keeps the rest verbatim, which suits agents whose tool output is bulky and dead; pair either with the memory tool for facts that must survive.

## System design prompt

"Design a support assistant for 50,000 conversations a day. Hit a monthly budget, and tell me what you would measure."

A short model outline:

- **Shape the traffic.** Say the assumptions first: six turns per conversation, a 4,100-token static prefix (system plus tools), 60-token user turns, 180-token replies. Without caching that is 6 x 4,160 + 240 x 15 = 28,560 input tokens and 1,080 output tokens per conversation, $0.136 at the list prices above, about $204,000 a month over 50,000 x 30 conversations. Ask for the gap between turns too, because it decides the cache TTL.
- **Cache the prefix.** Put the system prompt and tools first, byte-stable, with one breakpoint at the end of the system block, and the date or customer context in the user turn. If turns arrive within five minutes of each other, a 5-minute TTL roughly halves the bill; conversations that pause longer need a 1-hour TTL or no cache, and you price each class separately.
- **Route by difficulty.** Send intent classification and simple FAQ to Haiku 5.5, the main answer to Sonnet or Opus at a chosen effort, and escalate on a failure signal. State that you would verify the split with an eval, not assume it.
- **Batch what nobody waits for.** Summaries, tagging, quality scoring and knowledge-base refreshes go to the Batch API at half price, with a 1-hour cache write if they share a prefix.
- **Budget guards.** Cap `max_tokens`, set a per-conversation token ceiling, and alert on cost per resolved conversation, not on total spend.
- **Measure.** Cache hit ratio per route, cost per resolved conversation, input and output tokens per turn, p50 and p95 time to first token, escalation rate, and the share of requests that hit `max_tokens`.

Close with the trade you are making: caching adds a write premium on the first turn, routing adds an evaluation burden, batching adds latency, and you will show the numbers for each.

## Take-home shape

A good 2 to 4 hour take-home on this topic gives you a small client with a tool loop and a recorded or live transport, and asks for three things:

1. **Ledger output.** A cost ledger that prices every call from `usage`, including cache reads and writes, printed as a table with prompt tokens, cached percentage, output tokens and USD per label.
2. **Cache-hit evidence.** A run of ten or more requests with a shared prefix and the hit ratio showing the first request writes and later ones read, plus one deliberate break (for example a changed tool order) and what the ledger shows when it happens.
3. **A cost plan.** A one-page plan for a given scenario that prices at least three strategies, picks one, and states assumptions and risks, including the ones the model simplifies, such as batching combined with a short cache TTL.

Hand in the code, the ledger and hit-ratio output pasted as text, and the plan. Aim for correct arithmetic from `usage` fields, a cache claim backed by numbers, and honest caveats. The exercise `course/m0-cost-lab` is built in this shape, so doing its stages 01 to 07 is a rehearsal.
