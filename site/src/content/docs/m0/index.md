---
title: M0 Inference economics
freshness: skip
---

How inference cost and latency arise and the API levers that control them.

## Lessons

- [01 Tokens, prefill, decode](./01-tokens-prefill-decode/)
- [02 KV cache and batching](./02-kv-cache-and-batching/)
- [03 Prompt caching as prefix engineering](./03-prompt-caching/)
- [04 Cost levers: batch, effort, budgets, model choice](./04-cost-levers/)
- [05 Structured outputs and strict tools](./05-structured-outputs-and-strict-tools/)
- [06 Context management: compaction, editing, memory](./06-context-management/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M0 cost lab](/exercises/m0-cost-lab/): build a small cost-aware Claude client and prove its cache hits and its bill, with tests and hints.

1. `01-tool-loop`: a hand-written tool-use loop that returns all tool results in one user message.
2. `02-streaming`: streaming that ends in a complete final message.
3. `03-cache-prefix`: cache-aware prompt assembly with a byte-stable prefix.
4. `04-cost-ledger`: a cost ledger computed from usage, cache tokens included.
5. `05-batch-builder`: batch requests keyed by `custom_id` and a join that survives shuffled results.
6. `06-cost-plan`: a priced cost plan for a support assistant: a cache TTL per gap class, batch only where nobody waits, and a silent invalidator found in a request log (judgment stage).
7. `07-live-cache-hit`: a live check that ten requests actually hit the cache (needs an API key).
