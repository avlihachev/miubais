# Interview angle: observability and cost

**Prerequisites:** lessons 01 to 06 of [M3](../), which this page assumes you have read.

This page collects what lessons 01 to 06 prepare you to answer out loud. Each answer points back to the lesson that covers it in depth.

## What they ask

**1. What does the trace of one agent run look like?**
One root span, `invoke_agent ticket-runner`, for the whole run with the totals and the outcome, and under it, as siblings, one `chat {model}` span of kind `CLIENT` per model response and one `execute_tool {name}` span of kind `INTERNAL` per tool call. The Agent SDK does not hand you that tree: one response arrives as several messages sharing a `message_id`, tool results come back later in user messages, and no message carries a timestamp. So you stamp each message on arrival, make one chat span per message id, keep open tool calls in a table until their result arrives, and close any call that never returns with `error.type = "no_result"` so the trace shows where the run died ([lesson 01](../01-traces-and-spans-for-agents/)).

**2. Would you build on the GenAI semantic conventions, given their status?**
Yes, carefully. Every document in the GenAI conventions repository is at status Development, which allows breaking changes, and the Python constants live in an `_incubating` module. They are still the only shared vocabulary that backends map. Pin the semconv package with the SDK, import constants instead of typing strings, and keep the mapping in one function; the course already met one rename, the spec's `cache_write` against the installed `cache_creation`. For Anthropic, `gen_ai.usage.input_tokens` is the whole prompt: the API's `input_tokens` plus cache reads plus cache writes, because the API's figure excludes cached tokens. The two cache parts are also set on their own, since they have their own prices ([lesson 02](../02-genai-semantic-conventions/)).

**3. How do you get your spans into Langfuse, and what does it add over a plain tracing backend?**
The standard OTLP HTTP exporter pointed at `/api/public/otel/v1/traces`, with `Authorization: Basic` over the public and secret key and `x-langfuse-ingestion-version: 4`; no gRPC, no Langfuse SDK needed. Langfuse turns the root into an agent observation, chat spans into generations and tool spans into tool observations, and reads the `gen_ai.usage.*` attributes as first-class token fields. On top of storage it adds prompt management, datasets and experiments, and evaluations that run on production traces, which is where the M2 judge can score real traffic. Self-hosting keeps traces full of file paths and diffs inside your boundary, at the price of running Postgres, ClickHouse, Redis and object storage ([lesson 03](../03-langfuse-self-hosted/)).

**4. You compute cost from spans and the SDK reports `total_cost_usd`. Which do you trust?**
Neither is a bill: both are local estimates from a price table, and the SDK says so. On the recorded runs they agree to 1e-9 because the inputs agree. On live runs they diverge for known reasons: per-step output tokens are a placeholder from `message_start`, `usage` leaves out subagents, a budget stop omits the crossing response from `usage`, and a crash can zero every field. On the course's live run the SDK said 0.2074 USD and Langfuse, pricing the placeholder output, said 0.1179. Put your own cost on each span, take the run total from the result message, and reconcile the month against the Usage and Cost API ([lesson 04](../04-cost-per-task/)).

**5. Why have a client-side budget guard when the SDK has `max_budget_usd`?**
They cover each other's gaps. The guard is an observer that prices every new message id and stops the run on the first message that takes the estimate above the limit, mid-stream, before any result arrives; on a live stream its estimate is a floor, because output counts are placeholders. The SDK cap uses real counts and sees subagent spend, but it checks after a response arrives and lets the response that crosses the cap complete. Pass the same limit to both, or a lower one to the guard, and treat a `stopped_by="budget"` as an event worth an alert ([lesson 04](../04-cost-per-task/)).

**6. How do you route tickets across cheap and expensive models?**
An ordered list of routes, each a model with its own turn and spend caps, cheapest first. Fall back only on stops that more room could fix: `max_turns`, `budget` and `error`. A `policy` stop ends routing: the denial is about the action, and a stronger model may be better at finding a way around the hook, so the stage 05 router refuses a configuration that would fall back on it. `fallback_model` in the SDK is a different layer; it reacts to overload and unavailable models, not to a run that used up its room. Budget the ticket for the sum of all route caps, and judge each route by its eval pass rate and cost per passed ticket, not by how often it finishes ([lesson 05](../05-routing-and-fallback/)).

**7. Which single number explains most of the cost difference between similar tickets?**
The cache-hit ratio, cache reads over the whole prompt. A coding agent re-sends a growing prefix every turn, and a cached read costs 0.05x of input on Opus 5.5. On the course's 40 recorded runs the total is 4.87 USD; pricing cache reads as plain input would make it 13.61 USD. The cache breaks when anything early in the order `tools`, `system`, `messages` changes, when calls are more than five minutes apart, or when the prompt is under the minimum length, so a falling daily ratio often means someone changed a prompt or a tool definition for every ticket at once ([lesson 04](../04-cost-per-task/)).

**8. Time to first token or total latency: which do you optimise, and where do parallel tool calls fit?**
For an unattended factory, total latency per ticket sets throughput; time to first chunk is a diagnostic for prompt growth and cache misses. Measure it with `include_partial_messages`, stamp the first `content_block_delta` and record it as `gen_ai.response.time_to_first_chunk`, labelled as client-observed. Parallel tool calls arrive as several messages with one id: one chat span, one tool span per block, and the turn's tool time is the longest of them, not the sum. On the recorded runs 91.4% of wall time is in chat spans, so the levers are fewer turns, smaller prompts and a warm cache, not faster tools. Put a deadline around the whole run, because the SDK options bound turns and money but not time ([lesson 06](../06-latency-engineering/)).

## System design prompt

"Design observability and cost control for a factory that runs 300 agent tickets a day. What do you record, where does it go, what stops a run, and what do you alert on?"

A short model outline:

- **Instrument at one point.** The harness runner's observer sees every message in order. It stamps arrival times, builds the span tree (root, chat per message id, tool per call) with the GenAI attributes and the Anthropic input rule, puts a computed `gen_ai.usage.cost` on every chat span, and hosts the budget guard. The harness does not depend on a tracing library.
- **Ship without risking the run.** A batch processor and the OTLP HTTP exporter to a self-hosted Langfuse, with a short exporter timeout and no further batches after a failure, so a dead collector costs seconds and loses spans, never tickets. 300 tickets at a dozen turns and a few tool calls each is on the order of ten thousand spans a day, a small load for the stack.
- **Price per task and reconcile.** Cost per chat span from four token kinds at their own prices, deduplicated by message id, summed per run and per ticket, with the run total from the result message. Reconcile daily totals against the Usage and Cost API and treat a growing gap as a stale price table.
- **Stop runs in two layers.** A per-route budget enforced by the guard mid-stream and by `max_budget_usd` as the backstop, a turn cap, and a wall-clock deadline around the run. Size it with numbers: at the course's live run of about 0.21 USD a ticket on Opus, 300 tickets is roughly 60 USD a day before retries, and the worst case per ticket is the sum of the route caps.
- **Route by cost, gate by quality.** Cheapest route first, fallback on budget, turns and error only, never on policy. Per-route stats in the trace (`trace_lab.route`) and per-route pass rates from the M2 eval suite.
- **Alert on events and trends.** Per ticket: budget stops, cost above a multiple of its class median, a cache-hit drop. Per day: spend against budget, the number of budget stops, the mean cache-hit ratio, per-tool p90 and p99 latency and the chat share of wall time, and the reconcile gap. A weekly review of the costliest quarter of runs, since spend concentrates there.

Close with the trades: sampling traces saves storage but loses the rare expensive run you most need to see, so keep every root span and sample the detail if you must; a tighter guard stops more good runs; and every number above is an estimate until the billing API agrees with it.

## Take-home shape

A good 2 to 4 hour take-home on this topic hands the candidate a few dozen recorded agent runs as JSONL message streams with arrival times, a price table, and a small harness with an observer hook, and asks for three things:

1. **A span recorder with tests.** Code that turns one run into an OpenTelemetry span tree with GenAI attributes, tested on an in-memory exporter: one chat span per message id under parallel tool calls, the Anthropic input rule on a cached turn, and a cut-off run whose open tool call is still closed with an error type.
2. **Cost per task and a budget guard.** Cost from spans that matches the runs' reported cost, a cache-hit ratio per ticket, and an observer that stops a scripted run on the exact message whose estimate crosses the limit, with a test that no later message is consumed.
3. **A short cost review.** The five costliest tickets, the cause behind each with a cited run and line, the lever the candidate would pull first, and what they would alert on.

Grade on the edges (duplicate message ids, a limit exactly equal to the estimate, a run with no result), on whether cache tokens are priced at their own prices, on a guard that stops mid-run rather than at the result, and on a review that cites evidence instead of restating the totals. A submission that copies `input_tokens` as the prompt size, or checks the budget only when the run is over, fails.
