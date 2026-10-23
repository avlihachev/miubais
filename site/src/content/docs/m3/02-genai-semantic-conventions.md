---
title: GenAI semantic conventions
description: The OpenTelemetry GenAI attribute names for model, tool and agent spans, the Anthropic rule for input tokens, the cache attribute naming drift between the spec and the installed package, and what Langfuse reads.
module: m3
order: 2
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:opentelemetry-sdk": "1.45.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://opentelemetry.io/docs/specs/semconv/gen-ai/
    title: Semantic conventions for generative AI systems (moved notice)
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai
    title: OpenTelemetry GenAI semantic conventions repository
    checked: 2026-10-17
  - url: https://opentelemetry.io/docs/specs/otel/versioning-and-stability/
    title: Versioning and stability for OpenTelemetry clients
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md
    title: Semantic conventions for generative AI client inference
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md
    title: Semantic conventions for generative AI spans
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md
    title: Semantic conventions for GenAI agent and framework spans
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/anthropic.md
    title: Semantic conventions for Anthropic
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-token-metrics.md
    title: Semantic conventions for generative AI token metrics
    checked: 2026-10-17
  - url: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
    title: Semantic conventions for generative AI metrics
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
    title: Prompt caching
    checked: 2026-10-17
  - url: https://langfuse.com/integrations/native/opentelemetry
    title: OpenTelemetry (OTEL) for LLM Observability
    checked: 2026-10-17
---

**Prerequisites:** [lesson 01](../01-traces-and-spans-for-agents/), which builds the span tree whose attributes this lesson names.

## Why this matters for the factory

A span tree tells you that the third turn took eight seconds. It does not tell you what that turn cost or which model ran it until the spans carry attributes, and attributes are only useful if every tool that reads them agrees on the names. If your harness writes `tokens_in`, your backend shows nothing in its token column, your cost dashboard needs a custom mapping, and the next team's harness writes `prompt_tokens`. A factory runs many harnesses against several backends over years, so the attribute names are an interface, and the GenAI semantic conventions are the closest thing to a shared one.

Every document in the GenAI conventions is at status Development, the cache write name already differs between the spec and the installed package, and the Python package you install can lag the spec. This lesson shows the names the course uses, the Anthropic rule for input tokens, and where the installed constants and the current spec disagree.

## Core idea

The GenAI conventions now live in their own repository. The opentelemetry.io page says "GenAI semantic conventions have moved to the OpenTelemetry GenAI semantic conventions repository" and points to `github.com/open-telemetry/semantic-conventions-genai`. Each document in it opens with "**Status**: Development" (checked for the client inference, spans, agent spans, Anthropic, token metrics and metrics documents).

OpenTelemetry's stability page says that for something in Development "breaking changes and performance issues MAY occur", that it "MAY be discarded and removed entirely", and that "Long-term dependencies SHOULD NOT be taken against signals in Development" (Versioning and stability). In Python the constants sit in a module path that says the same thing: `opentelemetry.semconv._incubating.attributes.gen_ai_attributes`, from `opentelemetry-semantic-conventions` 0.66b1, a beta release that `opentelemetry-sdk` 1.45.1 installs.

For a factory that means three things. Import names from the installed constants rather than typing strings, so an upgrade is a diff you can see. Pin the semconv package with the SDK. And keep the mapping from your harness to attributes in one function, so a rename touches one place. The exercise's stage 01 does all three.

## Mechanics

### The attributes the course sets

The inference span is `{gen_ai.operation.name} {gen_ai.request.model}` with kind `CLIENT`, which "MAY be set to `INTERNAL` on spans representing call to models running in the same process" (client inference). Requirement levels below are quoted from the client inference, spans and agent spans documents; the names are the installed 0.66b1 constants except where the row says otherwise.

| attribute | where | level in the spec | course value |
| --- | --- | --- | --- |
| `gen_ai.operation.name` | all | Required | `chat`, `execute_tool`, `invoke_agent` |
| `gen_ai.provider.name` | chat | Required | `anthropic` |
| `gen_ai.request.model` | chat | Conditionally Required, if available | the message's `model` |
| `gen_ai.response.model` | chat | Recommended | the message's `model` |
| `gen_ai.response.id` | chat | Recommended | the `message_id` |
| `gen_ai.response.finish_reasons` | chat | Recommended | `[stop_reason]` |
| `gen_ai.usage.input_tokens` | chat, root | Recommended | Anthropic rule, below |
| `gen_ai.usage.output_tokens` | chat, root | Recommended | `output_tokens` |
| `gen_ai.usage.cache_read.input_tokens` | chat, root | Recommended, when applicable | `cache_read_input_tokens` |
| `gen_ai.usage.cache_creation.input_tokens` (installed) / `gen_ai.usage.cache_write.input_tokens` (spec) | chat, root | Recommended, when applicable | `cache_creation_input_tokens` |
| `gen_ai.tool.name` | tool | Required | the tool name |
| `gen_ai.tool.call.id` | tool | Recommended, if available | the `tool_use` id |
| `gen_ai.conversation.id` | root | Conditionally Required | the session id |
| `gen_ai.agent.name` | root | Conditionally Required, when available | `ticket-runner` |
| `error.type` | any | Conditionally Required, if the operation ended in an error | `tool_error`, `no_result`, `error_max_turns`, ... |

The spec's agent span is `invoke_agent {gen_ai.agent.name}`, with kind `CLIENT` for a remote agent and `INTERNAL` for one in the same process (agent spans). The course's root is the harness's own view of the run, so it is an internal span. `error.type` marks a failed span; the course sets it together with an `ERROR` status, so a backend that filters on status and one that filters on the attribute both find the same spans. `gen_ai.request.max_tokens` and `gen_ai.request.reasoning.level` are in the spec too; the Anthropic document says the latter "Corresponds to the `output_config.effort` request parameter". The Agent SDK's messages do not expose them, so the course leaves them out.

### The Anthropic input token rule

Anthropic's usage block splits the prompt into three parts. The prompt caching page defines `input_tokens` as the tokens "which were not read from or used to create a cache (that is, tokens after the last cache breakpoint)", alongside `cache_read_input_tokens` and `cache_creation_input_tokens`, and gives the total as `total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens`.

The conventions want the total. The client inference document says `gen_ai.usage.input_tokens` "SHOULD include all types of input tokens, including cached tokens", and the cache attributes' notes say their values "SHOULD be included in `gen_ai.usage.input_tokens`". The Anthropic document makes it explicit: "Anthropic `input_tokens` excludes cached tokens", so compute "`gen_ai.usage.input_tokens = input_tokens + cache_read_input_tokens + cache_write_input_tokens`", and it requires that "`gen_ai.provider.name` MUST be set to `"anthropic"`".

A worked example with the numbers from the sample below. A later turn reports `input_tokens: 12`, `cache_read_input_tokens: 9000`, `cache_creation_input_tokens: 1500`. The prompt the model saw was 12 + 9000 + 1500 = 10,512 tokens. Copy the API field and the span says 12, which makes every cached turn look nearly free and makes a prompt that grows from turn to turn look flat. The three parts still go on the span separately, because they have different prices: lesson 04 prices cache reads and writes at their own rates, and the cache attributes are what make that possible.

Sample: `site/samples/m3/02-1.py`.

```python
from trace_lab_lessons import anthropic_input_tokens, inference_attributes

turns = {
    "first turn, cache written": {
        "input_tokens": 3,
        "output_tokens": 640,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 9000,
    },
    "later turn, cache hit": {
        "input_tokens": 12,
        "output_tokens": 210,
        "cache_read_input_tokens": 9000,
        "cache_creation_input_tokens": 1500,
    },
    "no caching at all": {
        "input_tokens": 10512,
        "output_tokens": 210,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    },
}

for label, usage in turns.items():
    print(
        f"{label:<26} api input_tokens={usage['input_tokens']:>5}  "
        f"gen_ai.usage.input_tokens={anthropic_input_tokens(usage):>5}"
    )

print()
attributes = inference_attributes(
    "claude-opus-5-5",
    turns["later turn, cache hit"],
    response_id="msg_example",
    finish_reason="tool_use",
)
for key, value in attributes.items():
    print(f"{key} = {value!r}")
```

The usage dicts are invented. `inference_attributes` comes from `course/m3-trace-lab/lesson_support/` and builds its keys from the installed constants (`GEN_AI_USAGE_INPUT_TOKENS`, `GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS` and the rest). Run it with `PYTHONPATH=course/m3-trace-lab/starter/src:course/m3-trace-lab/lesson_support/src uv run --frozen python site/samples/m3/02-1.py`.

Output, run on 2026-10-17:

```
first turn, cache written  api input_tokens=    3  gen_ai.usage.input_tokens= 9003
later turn, cache hit      api input_tokens=   12  gen_ai.usage.input_tokens=10512
no caching at all          api input_tokens=10512  gen_ai.usage.input_tokens=10512

gen_ai.operation.name = 'chat'
gen_ai.provider.name = 'anthropic'
gen_ai.request.model = 'claude-opus-5-5'
gen_ai.response.model = 'claude-opus-5-5'
gen_ai.usage.input_tokens = 10512
gen_ai.usage.output_tokens = 210
gen_ai.usage.cache_read.input_tokens = 9000
gen_ai.usage.cache_creation.input_tokens = 1500
gen_ai.response.id = 'msg_example'
gen_ai.response.finish_reasons = ['tool_use']
```

The second and third turns send the same 10,512-token prompt and get the same `gen_ai.usage.input_tokens`, because input size is a property of the prompt, and caching is a property of how it was billed. The API's own `input_tokens` differs by a factor of 876 between them.

### The naming drift, and the course's choice

The current spec documents name the write side `gen_ai.usage.cache_write.input_tokens` (client inference, Anthropic). The installed `opentelemetry-semantic-conventions` 0.66b1 has no such constant; it has `GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS = "gen_ai.usage.cache_creation.input_tokens"`. The Anthropic document's formula also writes the API field as `cache_write_input_tokens`, while the API itself calls it `cache_creation_input_tokens` (Prompt caching).

The course uses the installed constant, `gen_ai.usage.cache_creation.input_tokens`. The code imports names rather than typing them, the exercise's tests expect the exact string that constant produces, and the exercise pins the package; writing the spec's newer string by hand would put one literal next to a dozen imported names and would silently stop matching when the package catches up. When a later semconv release adds the `cache_write` constant, the change is one line in the attribute mapping and one in the cost reader. Until then, a backend or query that expects `cache_write` will see no cache writes from this harness, so check which name your backend reads.

Metrics show the same gap. The spec's token metrics document defines counters with unit `{token}`: `gen_ai.client.inference.usage.input_tokens`, `.output_tokens`, `.cache_read.input_tokens`, `.cache_write.input_tokens` and `.reasoning.output_tokens`, with required attributes `gen_ai.operation.name`, `gen_ai.provider.name` and `gen_ai.token.modality` ("The modality of the tokens being counted", values `text`, `image`, `audio`, `unknown`). The input counter is "including cached tokens", and the cache counters are each "a subset of `gen_ai.client.inference.usage.input_tokens`". The installed 0.66b1 metrics module (`opentelemetry.semconv._incubating.metrics.gen_ai_metrics`) still offers the older `GEN_AI_CLIENT_TOKEN_USAGE` and the attribute `gen_ai.token.type`, and none of the `inference.usage` counters. The metrics document also says `gen_ai.client.operation.duration` "SHOULD NOT be reported for inference operations; use `gen_ai.client.inference.duration` instead". The course does not emit metrics: the spans carry the same numbers, and the backend in lesson 03 ingests traces.

### What Langfuse reads

Langfuse's OpenTelemetry page lists the GenAI attributes it maps onto its own observation fields: `gen_ai.request.model` and `gen_ai.response.model` for the model, `gen_ai.usage.*` for usage, `gen_ai.usage.cost` for cost (as the `total`), `gen_ai.prompt` and `gen_ai.completion` for input and output, and `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result` as input and output when nothing else is set. Its own `langfuse.*` attributes "always take precedence over the generic OpenTelemetry conventions" (OpenTelemetry (OTEL) for LLM Observability). The course sends no prompt or completion text, only names, counts and ids, which keeps code and secrets out of the backend. Stage 04 adds `gen_ai.usage.cost` to each chat span so Langfuse shows the course's cost instead of computing its own; lesson 03 shows what happens when it computes its own from a live stream.

## Common pitfalls

- **Copying Anthropic's `input_tokens` into `gen_ai.usage.input_tokens`.** That is the uncached tail only. Add both cache parts, and report them separately as well.
- **Pricing the conventions' input total at the input price.** Once the total includes cache reads and writes, `input * price` overcharges reads and undercharges writes. Price from the three parts.
- **String literals for attribute names.** A rename in the spec then fails silently. Import the constants and pin the package.
- **Assuming the spec page and the installed package agree.** In 0.66b1 they differ from the spec on the cache write name and on the token metrics. Read the constant you emit, and check which one your backend maps.
- **Treating Development conventions as stable.** Keep the mapping in one function and expect to touch it on upgrades.
- **Recording prompts and completions by default.** `gen_ai.prompt` and `gen_ai.completion` will carry source code and anything in the context into the backend. Opt in deliberately.

## What interviewers ask

**What does `gen_ai.usage.input_tokens` mean for an Anthropic call?**
The whole prompt: the API's `input_tokens` plus `cache_read_input_tokens` plus `cache_creation_input_tokens`, because Anthropic's `input_tokens` excludes cached tokens. The cache parts also go on the span separately because they are priced differently.

**The GenAI conventions are at status Development. Would you still use them?**
Yes, with care: they are the only shared vocabulary that backends map, and the alternative is a private schema. Pin the package, import constants, and keep the mapping in one place so a rename is a small diff.

**Which attributes would you require on every model span?**
`gen_ai.operation.name` and `gen_ai.provider.name`, which the spec requires, plus the request model, the response id, the four token counts and `error.type` on failure. Those are enough to price a call, find it again and filter failures.

**Why send cost as an attribute when the backend can compute it?**
The backend's price table and token reading may not match yours, and on a live stream the per-step output count is a placeholder. Sending `gen_ai.usage.cost` makes the dashboard show the number your budget logic used.

**How would you handle a spec rename like `cache_creation` to `cache_write`?**
Upgrade the semconv package, change the one mapping function, and for a transition period emit both names or teach the backend both, so dashboards built on the old name keep working.

## Sources

- [Semantic conventions for generative AI systems](https://opentelemetry.io/docs/specs/semconv/gen-ai/), the moved notice, checked 2026-10-17
- [OpenTelemetry GenAI semantic conventions repository](https://github.com/open-telemetry/semantic-conventions-genai), checked 2026-10-17
- [Versioning and stability for OpenTelemetry clients](https://opentelemetry.io/docs/specs/otel/versioning-and-stability/), checked 2026-10-17
- [Semantic conventions for generative AI client inference](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/client-inference.md), status Development, checked 2026-10-17
- [Semantic conventions for generative AI spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md), status Development, checked 2026-10-17
- [Semantic conventions for GenAI agent and framework spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md), status Development, checked 2026-10-17
- [Semantic conventions for Anthropic](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/anthropic.md), status Development, checked 2026-10-17
- [Semantic conventions for generative AI token metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-token-metrics.md), status Development, checked 2026-10-17
- [Semantic conventions for generative AI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md), status Development, checked 2026-10-17
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), checked 2026-10-17
- [OpenTelemetry (OTEL) for LLM Observability](https://langfuse.com/integrations/native/opentelemetry), Langfuse, checked 2026-10-17
- Course code (repository files, not web sources): the lesson helpers in `course/m3-trace-lab/lesson_support/src/trace_lab_lessons/`; the stage 01 attribute list in `course/m3-trace-lab/README.md`; the installed constants in `opentelemetry/semconv/_incubating/attributes/gen_ai_attributes.py` and `opentelemetry/semconv/_incubating/metrics/gen_ai_metrics.py` (opentelemetry-semantic-conventions 0.66b1)
