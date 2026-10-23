---
title: M3 Observability and cost
freshness: skip
---

Traces of agent runs with the OpenTelemetry GenAI conventions, a self-hosted Langfuse, cost per task, budgets, routing and latency.

## Lessons

- [01 Traces and spans for agents](./01-traces-and-spans-for-agents/)
- [02 GenAI semantic conventions](./02-genai-semantic-conventions/)
- [03 Langfuse, self-hosted](./03-langfuse-self-hosted/)
- [04 Cost per task](./04-cost-per-task/)
- [05 Routing and fallback](./05-routing-and-fallback/)
- [06 Latency engineering](./06-latency-engineering/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M3 trace lab](/exercises/m3-trace-lab/): instrument the ticket harness with OpenTelemetry spans, price every task from its spans, stop runs on a budget, export to a local Langfuse and route tickets across models, with tests and hints.

1. `01-spans-from-messages`: turn a recorded message stream into a span tree with GenAI attributes and the Anthropic input token rule.
2. `02-cost-from-spans`: cost per task from chat spans, cache-hit ratios, and reconciliation with the SDK's estimate.
3. `03-budget-guard`: an observer that stops the run on the message whose estimate crosses the limit, with the SDK's cap as the backstop.
4. `04-otlp-export`: OTLP export to Langfuse with the right headers, surviving a collector that is down.
5. `05-model-router`: routes with fallback on budget, turns and errors, never on a policy stop, and per-route stats.
6. `06-top-costly`: the costliest tasks with their cache-hit ratios, as a table and a CLI.
7. `07-cost-review`: name the cause and the lever for the five costliest tickets, with evidence from the runs (judgment stage).
8. `08-live-traced-ticket`: one tinyshop ticket traced into a local Langfuse and read back (needs Docker and a Claude login).
