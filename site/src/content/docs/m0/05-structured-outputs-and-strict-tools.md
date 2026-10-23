---
title: Structured outputs and strict tools
description: Get machine-readable results without parse-and-retry loops, using output_config.format, strict tool schemas, correct tool-result plumbing, and guarded parsing of streamed tool input.
module: m0
order: 5
verified_on: 2026-10-17
executed: local
pins:
  "pypi:anthropic": "1.15.0"
  "pypi:pydantic": "2.14.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
    title: Structured outputs
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use
    title: Strict tool use
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools
    title: Define tools
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
    title: Handle tool calls
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use
    title: Parallel tool use
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming
    title: Fine-grained tool streaming
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/citations
    title: Citations
    checked: 2026-10-17
---

**Prerequisites:** [lesson 01](../01-tokens-prefill-decode/) for `stop_reason` and `max_tokens`, and a first tool-use call of your own.

## Why this matters for the factory

A factory is a pipeline of programs, and the model sits between them. A triage step emits a label that a router reads, a planner emits a task list that a scheduler reads, a coding agent emits tool calls that your sandbox executes. Every time the output does not parse, or parses into the wrong shape, you pay for the request again, plus whatever ran on the bad data before someone noticed. Take, as an illustration, a step that runs 100,000 times a day and fails to parse 2% of the time: that is 2,000 retries a day, each re-sending the full prompt, and some of those failures do not raise: a missing optional field or a string `"2"` where your code expected `2` flows downstream.

Constrained decoding removes most of that class of failure at the source. This lesson covers the two places it applies on the Claude API, the final response and tool inputs, the limits of what it guarantees, and the plumbing around tool calls that still breaks loops when it is done wrong: parallel results, error results, and streamed inputs that you must validate yourself. One change matters if you learned the older pattern of forcing a tool to get JSON: on Opus 5.5 and Sonnet 5.5, forced `tool_choice` returns 400 (Define tools).

## Core idea

There are three channels through which a model returns something your code consumes, and each has its own guarantee.

| channel | how you ask | what is guaranteed |
| --- | --- | --- |
| final response | `output_config.format` (`json_schema`) | text block is JSON matching the schema* |
| tool inputs | `tools[i].strict = true` | tool name valid, input matches `input_schema`* |
| everything else | prompt instructions | nothing; validate and handle failure |

\* except refusal, `max_tokens`, enum casing

Both guarantees come from the same mechanism: the API compiles your JSON Schema into a grammar and constrains token sampling to what the grammar allows (Structured outputs; Strict tool use). The model cannot emit a token that would make the output invalid, so there is no parse error to retry. The grammar applies only to the model's direct output; thinking and tool results are not constrained, and the grammar state resets between sections, so the model can reason freely and still produce a valid final object.

The first request with a new schema pays extra latency while the grammar compiles; compiled grammars are cached for 24 hours from last use, and changing only `name` or `description` fields does not invalidate them. The API injects a system prompt describing the format, so input tokens rise slightly, and changing `output_config.format` invalidates the prompt cache for that conversation (Structured outputs). The guarantee breaks in three documented cases: `stop_reason: "refusal"` (the refusal takes precedence over the schema), `stop_reason: "max_tokens"` (the object is cut off), and the capitalisation of string `enum` and `const` values, which may differ from the schema in the first letter of a word after a space. Your code still checks `stop_reason` and compares enums case-insensitively.

## Mechanics

### Requesting a schema-shaped response

Send `output_config={"format": {"type": "json_schema", "schema": {...}}}` on `messages.create` and the reply's text block is JSON that matches the schema. In Python the recommended path is `client.messages.parse(..., output_format=PydanticModel)`: the SDK converts the model to a schema, sends it as `output_config.format`, validates the response and returns the instance in `parsed_output` (Structured outputs). The older top-level `output_format` request parameter is deprecated, needs the `structured-outputs-2025-11-13` beta header to work at all, and the SDK raises `TypeError` if you pass it to `client.beta.messages.create`; the `output_format=` argument of `parse()` is the SDK's own and is fine.

The supported schema subset is narrower than full JSON Schema. Every object needs `additionalProperties: false`. Numeric constraints (`minimum`, `maximum`, `multipleOf`), string length constraints, array constraints beyond `minItems` of 0 or 1, recursive schemas and external `$ref` are not supported and return 400 if sent raw. The SDK's transformation removes unsupported constraints, appends them to the field description, sends the simplified schema, and then validates the response against your original constraints in your process, so a Pydantic `Field(ge=100)` is still enforced, just client-side. Required properties are emitted first, then optional ones, each group in schema order.

### Strict tools and the end of forced tool choice

Setting `"strict": true` on a tool definition, next to `name`, `description` and `input_schema`, guarantees that the tool name is valid and the `input` matches the schema: `passengers: 2`, never `"2"` or `"two"` (Strict tool use). The schema rules are the same: `additionalProperties: false` on every object, and list in `required` whatever your function cannot default. Complexity limits apply per request, summed across all strict schemas and the output format: at most 20 strict tools, 24 optional parameters and 16 parameters with union types (`anyOf` or type arrays), with a 180-second compilation timeout behind them (Structured outputs). Optional parameters are the expensive part, each one roughly doubling a portion of the grammar's state space, so make parameters required and let the model supply defaults.

Before strict tools, a common way to get JSON was `tool_choice: {"type": "tool", "name": "emit_result"}`. On Opus 5.5, Sonnet 5.5, Fable 5.1 and Mythos 5.1, `tool_choice` of type `any` or `tool` returns 400 regardless of thinking settings; `auto` and `none` still work (Define tools). The documented replacement is `auto` with strict tools when you need valid tool inputs, and `output_config.format` when you need a response in a fixed shape. Which tool `auto` picks remains promptable, so say in the system prompt when each tool should be used.

### The loop, a strict tool on the wire, and a parsed response

The sample runs a minimal hand-written loop, `tool_loop` from `course/m0-cost-lab/lesson_support/` (helpers written for these lessons, not the exercise solution), with two strict tools, then asks for a typed report with `messages.parse`. All three model calls go through `cost_lab.transport.make_client`, which replays recorded fixtures instead of calling the API: `loop_turn1` (the model calls `get_price` and `get_stock` in parallel), `loop_turn2` (the final answer) and `structured_ok`, a synthetic fixture with a JSON text block. Their contents and usage are synthetic, so the sample shows request and response shapes, not model behaviour. Run it from the repository root with `PYTHONPATH=course/m0-cost-lab/starter/src:course/m0-cost-lab/lesson_support/src uv run --frozen python site/samples/m0/05-1.py`.

Sample: `site/samples/m0/05-1.py`.

```python
import json
from pathlib import Path

from cost_lab.transport import make_client
from cost_lab_lessons import tool_loop
from pydantic import BaseModel

FIXTURES = Path("course/m0-cost-lab/fixtures")
MODEL = "claude-opus-5-5"
SKU_SCHEMA = {
    "type": "object",
    "properties": {"sku": {"type": "string", "description": "Catalogue id such as A1."}},
    "required": ["sku"],
    "additionalProperties": False,
}
TOOLS = [
    {
        "name": "get_price",
        "description": "Unit price in EUR for a SKU.",
        "strict": True,
        "input_schema": SKU_SCHEMA,
    },
    {
        "name": "get_stock",
        "description": "Units in stock for a SKU.",
        "strict": True,
        "input_schema": SKU_SCHEMA,
    },
]
CATALOGUE = {"A1": {"get_price": "12.50", "get_stock": "7"}}


def execute(name: str, tool_input: dict) -> str:
    return CATALOGUE[tool_input["sku"]][name]


class StockReport(BaseModel):
    sku: str
    price_eur: float
    in_stock: int
    reorder: bool


client, transport = make_client(FIXTURES, ["loop_turn1", "loop_turn2", "structured_ok"])
final_text, turns = tool_loop(
    client,
    model=MODEL,
    max_tokens=16000,
    system="Answer stock questions. Call every lookup you need in the same turn.",
    tools=TOOLS,
    messages=[{"role": "user", "content": "Price and stock of A1?"}],
    execute=execute,
)
print("loop:", turns, "turns,", repr(final_text))
second = transport.requests[1].body
print("tool results in one user message:", json.dumps(second["messages"][-1]))
print("strict tool on the wire:", json.dumps(second["tools"][0]))

report = client.messages.parse(
    model=MODEL,
    max_tokens=16000,
    output_format=StockReport,
    messages=[
        {
            "role": "user",
            "content": f"Turn this into a stock report: {final_text}. Reorder below 10 units.",
        }
    ],
)
print("output_config sent:", json.dumps(transport.requests[2].body["output_config"]))
print("parsed:", repr(report.parsed_output), "stop_reason:", report.stop_reason)
```

Output, run on 2026-10-17:

```
loop: 2 turns, 'A1 costs 12.50 and 7 are in stock'
tool results in one user message: {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01", "content": "12.50"}, {"type": "tool_result", "tool_use_id": "toolu_02", "content": "7"}]}
strict tool on the wire: {"name": "get_price", "description": "Unit price in EUR for a SKU.", "strict": true, "input_schema": {"type": "object", "properties": {"sku": {"type": "string", "description": "Catalogue id such as A1."}}, "required": ["sku"], "additionalProperties": false}}
output_config sent: {"format": {"schema": {"type": "object", "title": "StockReport", "properties": {"sku": {"type": "string", "title": "Sku"}, "price_eur": {"type": "number", "title": "Price Eur"}, "in_stock": {"type": "integer", "title": "In Stock"}, "reorder": {"type": "boolean", "title": "Reorder"}}, "additionalProperties": false, "required": ["sku", "price_eur", "in_stock", "reorder"]}, "type": "json_schema"}}
parsed: StockReport(sku='A1', price_eur=12.5, in_stock=7, reorder=False) stop_reason: end_turn
```

First, the second request carries both tool results in a single user message, in the order of the `tool_use` blocks. The Parallel tool use page calls a separate user message per result the most common reason parallel calls stop happening: the history "teaches" the model to call one tool at a time. The Handle tool calls page adds the ordering rules: `tool_result` blocks must immediately follow the assistant message with the matching `tool_use` blocks, they come first in the user message's content, and any text goes after them. Second, `execute` receives `block.input` as the SDK delivered it, a parsed `dict`; never re-serialise it and pick it apart with string operations, and with a strict schema you can index `tool_input["sku"]` without defensive checks. Third, `parse()` turned the Pydantic model into a schema with `additionalProperties: false` and every field required, and `parsed_output` is a typed instance.

The lesson loop keeps only the happy path. A production loop also needs the error path: when a tool raises, send back a `tool_result` with the exception text as `content` and `"is_error": true`, so the model sees the failure and can retry with different input or explain it, instead of the loop crashing or the model receiving an empty result it might read as success. Stage `01-tool-loop` of the exercise asks you to build that.

### Streamed tool input is yours to validate

For tools that take a large argument, a file body or a patch, waiting for the API to buffer and validate the whole input delays the first byte. Setting `"eager_input_streaming": true` on a user-defined tool, with streaming enabled, makes the API send `input_json_delta` fragments as they are generated, without buffering or validation (Fine-grained tool streaming). The price is that the accumulated string might not be valid JSON, and a response that stops at `max_tokens` can cut a parameter off midway. Concatenate the `partial_json` fragments, parse once at `content_block_stop`, guard the parse, and return a failure to the model as an error result. The documented convention for unparseable input is a JSON object with an `INVALID_JSON` key holding the raw string, with `is_error: true`. The sample below needs no model call; it shows the tool definition and the handler for three inputs: valid, truncated, and well-formed but missing a required field.

Sample: `site/samples/m0/05-2.py`.

```python
import json

from pydantic import BaseModel, ValidationError

WRITE_FILE = {
    "name": "write_file",
    "description": "Write a whole file to the workspace.",
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}


class WriteFile(BaseModel):
    path: str
    content: str


def error_result(tool_use_id: str, payload: dict) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(payload),
        "is_error": True,
    }


def tool_result(tool_use_id: str, raw_input: str) -> dict:
    try:
        args = WriteFile.model_validate(json.loads(raw_input))
    except json.JSONDecodeError:
        return error_result(tool_use_id, {"INVALID_JSON": raw_input})
    except ValidationError as exc:
        return error_result(
            tool_use_id, {"INVALID_INPUT": [f"{e['loc'][0]}: {e['msg']}" for e in exc.errors()]}
        )
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": f"wrote {len(args.content)} chars to {args.path}",
    }


print(tool_result("toolu_01", '{"path": "app.py", "content": "print(1)\\n"}'))
print(tool_result("toolu_02", '{"path": "app.py", "content": "print(1'))
print(tool_result("toolu_03", '{"path": "app.py"}'))
```

Output, run on 2026-10-17 with `uv run --frozen python site/samples/m0/05-2.py`:

```
{'type': 'tool_result', 'tool_use_id': 'toolu_01', 'content': 'wrote 9 chars to app.py'}
{'type': 'tool_result', 'tool_use_id': 'toolu_02', 'content': '{"INVALID_JSON": "{\\"path\\": \\"app.py\\", \\"content\\": \\"print(1"}', 'is_error': True}
{'type': 'tool_result', 'tool_use_id': 'toolu_03', 'content': '{"INVALID_INPUT": ["content: Field required"]}', 'is_error': True}
```

Building the wrapper with `json.dumps` rather than string concatenation keeps quotes in the broken input escaped, as the Fine-grained tool streaming page advises. The same handler shape is worth having for non-streamed, non-strict tools too: the API does not promise those inputs match your schema.

### What structured outputs do not combine with

Citations require citation blocks interleaved with text, so enabling citations on any document or search result block together with `output_config.format` returns 400 (Citations; Structured outputs). If you need both grounded answers and a fixed shape, run two steps: a cited answer, then a structured extraction over it, or put the citation fields into your own schema and accept that they are model-written rather than API-verified. Message prefilling is also incompatible with JSON outputs. Batch processing, token counting and streaming all work with structured outputs, and JSON outputs and strict tools can be used together in one request.

## Common pitfalls

- **Forcing a tool on Opus 5.5 to get JSON.** `tool_choice: {"type": "tool", ...}` or `{"type": "any"}` returns 400 on Opus 5.5 and Sonnet 5.5. Use `output_config.format` for the response shape, or `auto` with a strict tool and a system prompt that says when to call it.
- **One user message per tool result.** It is accepted but steers the model away from parallel calls, adding a round trip per tool. Return all results of a turn in one user message, results first, text after.
- **Treating a schema-valid object as a successful one.** A refusal or a `max_tokens` stop can return output that does not match. Check `stop_reason` before you parse, and raise `max_tokens` if objects are cut off.
- **Exact enum comparison.** `"Conversation Topic 3"` can come back for a schema value of `"Conversation topic 3"`. Compare case-insensitively and avoid enum values that differ only in case.
- **Twenty optional fields "for flexibility".** Optional and union parameters drive grammar size; past 24 optional parameters per request the API refuses, and below that, first-request latency grows. Make fields required, flatten nesting, and mark only the tools where violations hurt as strict.
- **Trusting eagerly streamed input.** With `eager_input_streaming` the input is unvalidated and may be truncated. Parse once at block stop, validate against your model, and answer with `is_error: true` when it fails.

## What interviewers ask

**How do structured outputs guarantee valid JSON, and where does the guarantee stop?**
The API compiles the JSON Schema into a grammar and constrains sampling so only schema-valid tokens can be produced. It does not hold when the model refuses, when the response hits `max_tokens`, or for the capitalisation of enum values, so code still checks `stop_reason` and normalises enums.

**What is the difference between `output_config.format` and `strict: true`?**
The first constrains what the model says in its final response; the second constrains the arguments it passes when it calls one of your tools. They solve different problems and can be combined, for example an agent that calls strict tools and finishes with a schema-shaped report.

**How do you make a model call a particular tool on Opus 5.5?**
You cannot force it: `tool_choice` of type `any` or `tool` returns 400 there. You keep `auto`, describe in the prompt when the tool should be used, mark it strict so the call is valid when it happens, and if all you wanted was a shaped result, use `output_config.format` instead of a tool.

**Your agent stopped making parallel tool calls after a refactor. Where do you look first?**
At how tool results go back: one user message per result, or text placed before the results, teaches the model to call tools serially. All results for a turn belong in a single user message, `tool_result` blocks first, each with the `tool_use_id` it answers.

**What changes when you enable eager input streaming on a tool?**
Tool input fragments arrive without server-side buffering or validation, which lowers time to the first fragment of a large argument. The client must accumulate fragments, guard the parse, validate against its own schema, and report invalid input back with `is_error: true`.

## Sources

- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), checked 2026-10-17
- [Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use), checked 2026-10-17
- [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools), checked 2026-10-17
- [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls), checked 2026-10-17
- [Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use), checked 2026-10-17
- [Fine-grained tool streaming](https://platform.claude.com/docs/en/agents-and-tools/tool-use/fine-grained-tool-streaming), checked 2026-10-17
- [Citations](https://platform.claude.com/docs/en/build-with-claude/citations), checked 2026-10-17
- Course code (repository files, not web sources): the lesson helpers in `course/m0-cost-lab/lesson_support/src/cost_lab_lessons/`, the recorded transport in `course/m0-cost-lab/starter/src/cost_lab/transport.py`, and the fixtures `loop_turn1`, `loop_turn2` and `structured_ok`
