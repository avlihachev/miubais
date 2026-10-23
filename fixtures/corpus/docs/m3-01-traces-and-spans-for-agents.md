# Traces and spans for agents

**Prerequisites:** [M1 lesson 01](../../m1/01-harness-is-loop-plus-policy/), which builds the ticket runner this module instruments.

## Why this matters for the factory

A factory that runs hundreds of tickets a day without a person at the terminal needs to answer three questions after the fact: where did the time go, where did the money go, and which step failed. The M1 harness answers a fourth, whether the run ended well, with a single report: a `stopped_by` value, a turn count and a cost. That report is enough to gate a run. It is not enough to fix one. A ticket that cost three times its siblings might have looped on one Bash command, re-read a large file every turn, or lost its prompt cache; the report shows the same total in all three cases.

A trace keeps the shape of the run. Each model call and each tool call becomes a timed record with a parent, so you can see that the third turn took eight seconds, that two tool calls ran in parallel, and that one Bash call never returned. If your own projects store token counts but never add them up, and have no tracing at all, this module starts from exactly that point. This lesson defines the trace you will build in stage 01 of the exercise. Lesson 02 names its attributes, lesson 03 ships it to a backend.

## Core idea

OpenTelemetry's own definition is short: "Traces give us the big picture of what happens when a request is made to an application", and "A span represents a unit of work or operation" (Traces). A span has a name, a parent span id ("empty for root spans"), start and end timestamps, attributes and a status. The root span is "the beginning and end of the entire operation".

For one agent run on one ticket, the course uses a tree two levels deep:

```
invoke_agent ticket-runner            root: the whole run, totals, outcome
├── chat claude-opus-5-5              one model response (one message_id)
├── execute_tool Grep                 tool_use until its tool_result
├── execute_tool Read
├── chat claude-opus-5-5
├── execute_tool Edit
└── ...
```

The names come from the GenAI semantic conventions, which lesson 02 covers in detail. The inference span name "SHOULD be `{gen_ai.operation.name} {gen_ai.request.model}`" with kind `CLIENT` (Semantic conventions for generative AI client inference); the tool span name "SHOULD be `execute_tool {gen_ai.tool.name}`" with kind `INTERNAL` (Semantic conventions for generative AI spans); the agent span name "SHOULD be `invoke_agent {gen_ai.agent.name}`" (Semantic conventions for GenAI agent and framework spans). OpenTelemetry defines a client span as "a synchronous outgoing remote call" and an internal span as an operation that does "not cross a process boundary" (Traces), which is why a model call is `CLIENT` and a tool the Claude Code process runs locally is `INTERNAL`.

Chat and tool spans are siblings under the root, not nested inside each other. A tool call is requested by one model response and its result is read by the next one, so it belongs to neither. Keeping them flat under the root also makes "sum of chat spans" and "sum of tool spans" two simple queries.

## Mechanics

### What the SDK gives you, and what it does not

The Agent SDK does not emit spans. It yields Python objects, and a span tree has to be derived from them. Three properties of that stream decide how.

**One response, several messages.** "Claude Code emits an `AssistantMessage` as each non-empty content block completes, so a response with a text block and a tool call yields two `AssistantMessage` objects. Each one carries only its own content block, and both share the same message ID" (Stream responses in real-time). The cost-tracking page says the same for usage: "When Claude uses tools in parallel, multiple messages share the same `id` with identical usage data" (Track cost and usage). So the unit for a chat span is a `message_id`, not an `AssistantMessage`. Making one span per message would count the same prompt three times for a turn with three parallel tool calls.

**Tool results arrive later, in a different message.** A `tool_use` block sits in an `AssistantMessage`; its result comes back in a `UserMessage` holding a `ToolResultBlock` with the matching `tool_use_id`. Between the two, other tool calls may finish first. A tool span has to stay open across messages and close when its own result shows up, which means keeping a table of open calls by id.

**No timestamps.** In claude-agent-sdk 0.2.168 the `AssistantMessage` dataclass has the fields `content`, `model`, `parent_tool_use_id`, `error`, `usage`, `message_id`, `stop_reason`, `session_id` and `uuid`; `UserMessage` has no time field either. Only the final `ResultMessage` carries durations (`duration_ms`, `duration_api_ms`), and only for the whole run. A span needs a start and an end, so something outside the SDK has to stamp each message as it arrives. The course's run files store that stamp as `t_ms`, milliseconds since the run started, and `harnesskit.testing.load_run` returns a list of `Timed(at_ms, message)`.

There is one more trap, which matters for cost rather than shape. "Per-step `output_tokens` is a placeholder": Claude Code builds each assistant message "from the usage the API reported when the response began", so the per-message count is the one at `message_start`, and the real output total is on the result message (Track cost and usage). A chat span built from a live stream therefore has correct input and cache counts and a wrong output count. The recorded runs in `fixtures/harness-runs/` carry real per-message output counts; the README of that directory says live streams do not. Lesson 04 deals with the consequence.

### The mapping rules

Given a list of `Timed` messages, the tree is built in one pass:

- The root starts at `t_ms` 0 and ends at the last message's `t_ms`.
- The first `AssistantMessage` with a new `message_id` opens and closes a `chat` span. It starts at the `t_ms` of the message before it and ends at its own `t_ms`. Later messages with the same id add nothing to the chat span.
- Each `ToolUseBlock` opens an `execute_tool` span at its message's `t_ms`, keyed by the block's id.
- Each `ToolResultBlock` closes the span with the same id at its `t_ms`, marked as an error when `is_error` is set.
- At the end, any tool span still open is closed at the last `t_ms` with `error.type = "no_result"`.

The chat rule is an approximation, and it is worth knowing which way it errs. The span covers the time from the previous event to the moment the response's first content block completed, the model's queueing and generation up to that block, plus whatever the harness did in between, so it slightly overstates model time. It is not exact time to first token. Lesson 06 measures that from stream events.

The last rule exists because runs get cut off. A budget guard stops the iterator, a process is killed, a connection drops; the streaming page notes that a cut tool call "doesn't" get its `content_block_stop` (Stream responses in real-time). An exporter only ships ended spans, so a span left open is not a slow span but a missing one, and the trace then shows a run that did nothing at the moment it actually died. Closing it with an explicit error keeps the failure visible.

### The observer: one tap for every message

In M1, `harnesskit.runner.run_ticket` consumed the stream and kept what the report needed. For this module it gained one parameter: `run_ticket(..., observer=fn)` calls `fn(message)` after each SDK message is stored, including the `UserMessage` tool results, and keeps every message on `RunReport.messages`. An observer that returns a truthy value stops the run (the runner leaves its `contextlib.aclosing` block, which ends the CLI process), and the report then says `stopped_by="budget"` with the note `stopped by observer` (`fixtures/harnesskit/README.md`).

That single tap is enough for this whole module. The budget guard in lesson 04 is an observer. A recorder is an observer, or a thin wrapper around the query function that stamps `t_ms` as each message arrives, which is what the live stage 08 does so that the guard stays the runner's observer. harnesskit itself has no OpenTelemetry dependency: the observer is a plain callable, and the spans are built from what it saw. That keeps tracing optional and keeps the M1 harness testable without a collector.

### Building the tree from a recorded run

The sample loads one recorded run and builds the tree with `span_tree` and `render_tree` from `course/m3-trace-lab/lesson_support/` (small helpers written for these lessons, with their own types; they apply the rules above without OpenTelemetry). The starter's `record_run`, which you implement in stage 01, raises `NotImplementedError` until you do, so the sample does not use it. No model is called; run it from the repository root with `PYTHONPATH=course/m3-trace-lab/starter/src:course/m3-trace-lab/lesson_support/src uv run --frozen python site/samples/m3/01-1.py`.

Sample: `site/samples/m3/01-1.py`.

```python
from collections import Counter

from harnesskit.testing import load_run
from trace_lab_lessons import render_tree, span_tree

timed = load_run("fixtures/harness-runs/runs/r018.jsonl")
kinds = Counter(type(item.message).__name__ for item in timed)
print("messages:", dict(sorted(kinds.items())))

nodes = span_tree(timed)
print(render_tree(nodes))
print("spans:", len(nodes), "chat:", sum(n.name.startswith("chat") for n in nodes))
```

Output, run on 2026-10-17 (columns: span, start, duration):

```
messages: {'AssistantMessage': 7, 'ResultMessage': 1, 'UserMessage': 6, 'dict': 1}
invoke_agent ticket-runner              0 ms  36807 ms
  chat claude-opus-5-5                  0 ms  11730 ms
  execute_tool Grep                 11730 ms    866 ms
  execute_tool Read                 11730 ms     57 ms
  execute_tool Read                 11730 ms    495 ms
  chat claude-opus-5-5              12596 ms   5303 ms
  execute_tool Edit                 17899 ms    233 ms
  chat claude-opus-5-5              18132 ms   5944 ms
  execute_tool Bash                 24076 ms    866 ms
  chat claude-opus-5-5              24942 ms   3282 ms
  execute_tool Bash                 28224 ms    323 ms
  chat claude-opus-5-5              28547 ms   8181 ms
spans: 12 chat: 5
```

Seven assistant messages became five chat spans: the first response asked for three tools at once and arrived as three messages with one `message_id`. The three tool spans start together and end in a different order from the one they were requested in (the first Read finished after 57 ms, the Grep after 866 ms), and the next chat span starts only when the last of them returned. The `dict` is the run file's meta line with the ticket and session ids, which becomes root attributes rather than a span. Model time dominates: the five chat spans cover about 34 of the 37 seconds.

## Pitfalls seen in the wild

- **One span per `AssistantMessage`.** Parallel tool calls and text-plus-tool responses arrive as several messages with one id and identical usage. Key chat spans by `message_id`, or every token count in the trace is inflated.
- **Timing from the processing loop instead of the arrival.** If you stamp messages after doing work on them, or stamp them in a batch at the end, every span duration is wrong. Stamp at the moment each message is yielded.
- **Leaking open spans.** A cut-off run leaves tool calls without results. Unended spans are never exported, so the most interesting traces, the failed ones, are the ones missing. Close them with an error type.
- **Trusting per-step `output_tokens` from a live stream.** It is the count at `message_start`. Use the result's `usage` or `model_usage` for output, and label any running estimate as a floor.
- **Nesting tool spans under chat spans.** A tool call is requested by one response and consumed by the next; putting it under either one makes a chat span's duration include tool time and double counts latency.
- **Instrumenting inside the agent instead of at the harness.** Spans emitted by tool code see one tool; the harness sees every message in order. Put the tap where the messages are.

## What interviewers ask

**What is a trace of an agent run, concretely?**
A root span for the whole run with one child per model response and one per tool call, each with start and end times, a parent id and attributes such as model, token counts and tool name. It answers where time and money went and which step failed, which a single run report cannot.

**Why can't you map Agent SDK messages to spans one to one?**
One response arrives as several messages sharing a `message_id`, tool results arrive later in separate user messages, and no message carries a timestamp. You need to deduplicate by id, keep open tool calls in a table until their results arrive, and stamp each message on arrival.

**How do you handle a tool call that never returns?**
Close its span at the end of the run with an explicit error type such as `no_result`. An unended span is never exported, so the trace would otherwise hide the exact step where the run died.

**Why are tool spans siblings of chat spans rather than children?**
The tool call happens between two model responses: one requests it, the next reads its result. Making it a child of either distorts that span's duration, and keeping both flat under the root makes per-kind sums trivial.

**Where do you put the instrumentation in a harness?**
At the one point that sees every message in order, here the runner's observer. It also hosts the budget guard, and keeping it a plain callable means the harness does not depend on a tracing library.

## Sources

- [Traces](https://opentelemetry.io/docs/concepts/signals/traces/), OpenTelemetry, checked 2026-10-17
- [Semantic conventions for generative AI client inference](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md), status Development, checked 2026-10-17
- [Semantic conventions for generative AI spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md), status Development, checked 2026-10-17
- [Semantic conventions for GenAI agent and framework spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md), status Development, checked 2026-10-17
- [Stream responses in real-time](https://code.claude.com/docs/en/agent-sdk/streaming-output), checked 2026-10-17
- [Track cost and usage](https://code.claude.com/docs/en/agent-sdk/cost-tracking), checked 2026-10-17
- Course code and records (repository files, not web sources): the lesson helpers in `course/m3-trace-lab/lesson_support/src/trace_lab_lessons/`; the observer and run-file format in `fixtures/harnesskit/README.md`; the recorded runs and their notes in `fixtures/harness-runs/README.md`; the message dataclasses in `claude_agent_sdk/types.py` (claude-agent-sdk 0.2.168)
