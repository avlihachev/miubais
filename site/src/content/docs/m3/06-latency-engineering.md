---
title: Latency engineering
description: Time to first chunk versus total time for an agent run, what include_partial_messages adds and in which order events arrive, parallel tool calls in the span recorder, timeouts at every layer, and tool latency percentiles from the recorded runs.
module: m3
order: 6
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:opentelemetry-sdk": "1.45.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/agent-sdk/streaming-output
    title: Stream responses in real-time
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/cost-tracking
    title: Track cost and usage
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md
    title: Semantic conventions for generative AI client inference
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
    title: Semantic conventions for generative AI metrics
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/tools-reference
    title: Tools reference
    checked: 2026-10-17
  - url: https://opentelemetry.io/docs/specs/otel/protocol/exporter/
    title: OpenTelemetry Protocol Exporter
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
    title: Prompt caching
    checked: 2026-10-17
---

**Prerequisites:** [lesson 01](../01-traces-and-spans-for-agents/), which builds the timed span tree this lesson measures.

## Why this matters for the factory

A factory's throughput is tickets per hour per worker. When a ticket takes twelve minutes instead of four, a fixed fleet clears a third of the queue, and a person waiting on a pull request waits three times as long. Latency also hides failures: a Bash call that hangs until a timeout looks like a slow run, not a broken one, unless something measures it. Without measurement, latency work can go after the wrong thing: tuning streaming when the time goes into tool calls, or parallelising tools when model turns take the time.

Spans show where the time goes. This lesson separates the two latencies that matter for an agent, shows what the SDK lets you observe about each, and puts a timeout on every layer that can stall.

## Core idea

An agent run's wall time is the sum of its turns, and each turn is model time followed by tool time. Model time splits again into time to first chunk (queueing and reading the prompt) and generation time (producing the output). Tool time is the longest tool call in the turn when calls run in parallel, and the sum when they run one after another.

Time to first chunk is what a person watching a chat interface feels. For an unattended agent it is mostly a diagnostic: when it grows, the prompt grew or the cache stopped hitting. Total time per ticket is what the factory pays for in throughput. The lesson 01 span tree measures both kinds of time: `chat` spans for the model, `execute_tool` spans for tools, the root for the whole run. Streaming events add the first-chunk timestamp inside a `chat` span.

## Mechanics

### What the SDK lets you see

By default the SDK "yields a complete `AssistantMessage` for each non-empty content block, such as a text block or a tool call, after Claude finishes generating that block" (Stream responses in real-time). A lesson 01 `chat` span therefore ends when the turn's first block is complete, and it starts at the message before it, so it covers the request, the first chunk and the generation of that block together. Nothing in the default stream separates them.

Setting `include_partial_messages=True` "causes the SDK to yield `StreamEvent` messages containing raw API events as they arrive, in addition to the usual `AssistantMessage` and `ResultMessage`" (Stream responses in real-time). The events are the API's own: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta` ("stop reason, usage") and `message_stop`. The order matters for a recorder, and the streaming page spells it out: "each `AssistantMessage` arrives before that block's `content_block_stop` event", giving

```
StreamEvent (message_start)
StreamEvent (content_block_start) - text block
StreamEvent (content_block_delta) - text chunks...
AssistantMessage - complete text block
StreamEvent (content_block_stop)
StreamEvent (content_block_start) - tool_use block
StreamEvent (content_block_delta) - tool input chunks...
AssistantMessage - complete tool_use block
StreamEvent (content_block_stop)
StreamEvent (message_delta)
StreamEvent (message_stop)
... tool executes ...
```

(Stream responses in real-time). So a recorder that wants the full model time of a turn should end the `chat` span at `message_stop`, not at the first `AssistantMessage`, and can stamp the first chunk at the turn's first `content_block_delta`. Three limits apply. "Stream events are emitted for the main session only; token-level deltas from subagents aren't forwarded" (Stream responses in real-time). A cut stream still delivers `message_stop`, but "A cut tool call doesn't" get its `content_block_stop`, so an open tool block at `message_stop` means incomplete input (Stream responses in real-time), the same case stage 01 closes with `error.type = "no_result"`. And the measurement is taken on your side of the CLI subprocess, so it includes the CLI's own overhead; label it as client-observed.

`message_delta` is also where live output counts appear. Per-step `output_tokens` on an `AssistantMessage` is a placeholder; to "watch a response's output count grow while it streams", set `include_partial_messages` "and read `usage` from each `message_delta` stream event" (Track cost and usage). Turning on partial messages therefore also fixes the output-token gap from lesson 04 on the span itself.

### Where the first chunk goes in the trace

The GenAI conventions define an attribute for it. `gen_ai.response.time_to_first_chunk` is "Recommended" "If the request was a streaming request", type double: "Time to first chunk in a streaming response, measured from request issuance, in seconds", and `gen_ai.request.stream` marks the request as streaming (Semantic conventions for generative AI client inference). The installed `opentelemetry-semantic-conventions` 0.66b1 has both as `GEN_AI_RESPONSE_TIME_TO_FIRST_CHUNK` and `GEN_AI_REQUEST_STREAM`. The same document defines histograms `gen_ai.client.inference.time_to_first_chunk` and `gen_ai.client.inference.time_per_output_chunk`, each with the note "This metric SHOULD be reported for streaming calls and SHOULD NOT be reported otherwise", and `gen_ai.client.inference.duration`, whose value "SHOULD be the same as the span duration" when reported next to an inference span. The metric names drift like the cache attribute in lesson 02: 0.66b1's constant `GEN_AI_CLIENT_OPERATION_TIME_TO_FIRST_CHUNK` has the value `gen_ai.client.operation.time_to_first_chunk`. Everything here is at status Development. For contrast, the server-side metric `gen_ai.server.time_to_first_token` "helps measure the time spent in the queue and the prefill phase" (Semantic conventions for generative AI metrics); a client cannot see that split, only the total until the first chunk.

The SDK does not tell you when it issued the request. The nearest client-side point is the message before the turn (the tool result or the query start), which is where the lesson 01 `chat` span already begins. Record the first chunk as seconds from that start and say in your docs that it includes the CLI.

### Parallel tool calls in the recorder

When the model asks for several tools in one turn, "all messages in that turn share the same ID" (Track cost and usage), one `AssistantMessage` per `tool_use` block. The lesson 01 recorder makes one `chat` span for the first message with a new id and one `execute_tool` span per `tool_use` block, each opened at its assistant message's time and closed at its own `tool_result`. The next `chat` span starts at the last message before it, the last tool result, so model time never includes tool time. For latency, the turn's tool time is the longest of its parallel spans, not their sum; summing tool spans over a run over-counts every parallel turn.

### Timeouts at every layer

Each layer that can stall needs its own limit, and the defaults are long.

- **The run.** `max_turns` ("Maximum agentic turns (tool-use round trips)") and `max_budget_usd` bound work and money, not time (Agent SDK reference - Python). `ClaudeAgentOptions` in 0.2.168 has no wall-clock limit for a run, so put a deadline around the whole call yourself and stop the iterator when it expires.
- **The API request.** Through `env`, `API_TIMEOUT_MS` is the "per-request timeout on the Anthropic client, in milliseconds. Default `600000`"; `CLAUDE_CODE_MAX_RETRIES` defaults to 10, and "Each retry gets its own `API_TIMEOUT_MS` window"; the stream watchdog's `CLAUDE_STREAM_IDLE_TIMEOUT_MS` "defaults to `300000`" (Agent SDK reference - Python). With partial messages on, a gateway's keep-alive pings arrive as `ping` stream events; "Read those frames as liveness rather than timing the session out on silence" (Agent SDK reference - Python).
- **Tools.** For Bash, `BASH_DEFAULT_TIMEOUT_MS` is "the default when Claude passes no timeout; two minutes out of the box", and `BASH_MAX_TIMEOUT_MS` sets the ceiling, "ten minutes out of the box" (Tools reference). A test suite that can hang needs its own, shorter limit inside the command.
- **The exporter.** The OTLP exporter spec gives a timeout as the "Maximum time the OTLP exporter will wait for each batch export. Default: 10s", and requires retries with "exponential back-off with jitter" on transient errors (OpenTelemetry Protocol Exporter). Stage 04 passes `timeout=5.0` and stops sending batches after the first failure, so a dead collector costs seconds and never the run.

With the defaults, one request can take ten minutes and be retried ten times. A factory worker with no outer deadline can sit on one ticket for hours.

### Measuring with spans

The sample computes tool span durations per tool name over all 40 recorded runs, using the lesson 01 tree, and prints percentiles plus two aggregates: how many tool turns ran calls in parallel, and what share of total run time sits in `chat` spans. Run it with `PYTHONPATH=course/m3-trace-lab/starter/src:course/m3-trace-lab/lesson_support/src uv run --frozen python site/samples/m3/06-1.py`.

Sample: `site/samples/m3/06-1.py`.

```python
from pathlib import Path

from harnesskit.testing import load_run
from trace_lab_lessons import parallel_turns, span_tree, tool_durations, tool_latency_table

spans, parallel, tool_turns, chat_ms, wall_ms = [], 0, 0, 0, 0
for path in sorted(Path("fixtures/harness-runs/runs").glob("r*.jsonl")):
    timed = load_run(path)
    spans += tool_durations(timed)
    counts = parallel_turns(timed)
    parallel, tool_turns = parallel + counts[0], tool_turns + counts[1]
    nodes = span_tree(timed)
    wall_ms += nodes[0].duration_ms
    chat_ms += sum(n.duration_ms for n in nodes if n.name.startswith("chat "))

print("tool span durations, ms, over 40 recorded runs")
print(tool_latency_table(spans))
print(f"turns with parallel tool calls: {parallel} of {tool_turns}")
print(f"share of wall time in chat spans: {chat_ms / wall_ms:.1%}")
```

Output, run on 2026-10-17:

```
tool span durations, ms, over 40 recorded runs
tool      n    p50    p90    p99    max
Bash    117    490    864    894    899
Edit     61    488    845    891    891
Grep     46    495    835    894    894
Read     79    519    825    870    870
unfinished (no_result, left out): 2
turns with parallel tool calls: 9 of 287
share of wall time in chat spans: 91.4%
```

The percentiles use the nearest-rank method, so each value is a duration that was observed. The two unfinished calls are the two cut-off runs lesson 04 leaves out of reconciliation; they are left out because their "duration" is only the time until the recording stopped. The recorded runs are synthetic and their README says each tool result arrives 50 to 900 ms after the call, so the flat distribution is a property of the generator. Real Bash calls that run tests have a long tail, and p99 matters more than p50 there.

On these runs 91% of wall time is model time, so faster tools would barely move the total. The levers are on the model side: fewer turns, smaller prompts and a warm cache, which prompt caching says "significantly reduces processing time and costs for repetitive tasks or prompts with consistent elements" (Prompt caching). The same measurement on your own runs may point elsewhere.

## Common pitfalls

- **Ending the `chat` span at the first `AssistantMessage`.** With several blocks per turn that cuts the model time short. With partial messages, end at `message_stop`.
- **Summing parallel tool spans as tool time.** The turn waited for the longest one, not the sum.
- **Calling client-observed first-chunk time server latency.** It includes the CLI subprocess and the network.
- **Relying on default timeouts.** Ten-minute requests with ten retries and two-minute Bash calls add up to hours per stuck ticket.
- **Treating `ping` stream events as silence.** They are liveness; a watchdog that resets only on content kills healthy runs behind a gateway.
- **Optimising tools when the model dominates.** Measure the chat share before choosing a lever.

## What interviewers ask

**What is the difference between time to first token and total latency for an agent, and which matters?**
Time to first token is queueing plus reading the prompt. Total latency is all turns, model and tools, end to end. For a chat interface the first matters; for an unattended factory the second sets throughput, and the first is a diagnostic for prompt growth and cache misses.

**How do you measure time to first chunk with the Agent SDK?**
Turn on `include_partial_messages`, take the turn's start from the previous message, stamp the first `content_block_delta`, and record it as `gen_ai.response.time_to_first_chunk` on the `chat` span. Say it is client-observed: the SDK does not expose the request issue time.

**How do parallel tool calls show up in the message stream and in your spans?**
As several `AssistantMessage`s with one message id, one per `tool_use` block. The recorder makes one `chat` span for the id and one tool span per block. Turn latency is the longest tool span; cost is counted once per id.

**Where do you put timeouts in an agent system?**
Around the whole run, which the SDK options do not cover; on API requests and retries; on tool commands; on the trace exporter so a dead collector cannot hold the run. Set each value explicitly.

**Your agent got slower last week. How do you find out why?**
Compare span distributions before and after: the `chat` share, turns per run, the first-chunk time and prompt sizes, the cache-hit ratio, and per-tool p90 and p99. The span that grew tells you whether it was the prompt, the model, or a tool.

## Sources

- [Stream responses in real-time](https://code.claude.com/docs/en/agent-sdk/streaming-output), Claude Agent SDK docs, checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), `ClaudeAgentOptions` and section Handle slow or stalled API responses, checked 2026-10-17
- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), Claude Agent SDK docs, checked 2026-10-17
- [Semantic conventions for generative AI client inference](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md), OpenTelemetry, status Development, checked 2026-10-17
- [Semantic conventions for generative AI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md), OpenTelemetry, status Development, checked 2026-10-17
- [Tools reference](https://code.claude.com/docs/en/tools-reference), section Timeout and output limits, Claude Code docs, checked 2026-10-17
- [OpenTelemetry Protocol Exporter](https://opentelemetry.io/docs/specs/otel/protocol/exporter/), OpenTelemetry specification, checked 2026-10-17
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), Claude API docs, checked 2026-10-17
- Course code and records (repository files, not web sources): stages 01 and 04 in `course/m3-trace-lab/README.md`; the lesson helpers in `course/m3-trace-lab/lesson_support/src/trace_lab_lessons/`; the recorded runs and their README in `fixtures/harness-runs/`
