# Tokens, prefill, decode

**Prerequisites:** you have made a Messages API call from Python and seen the `usage` field in the response ([Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)).

## Why this matters for the factory

An AI software factory pays for every task twice: once in dollars and once in wall-clock time. Both bills are set by the same two phases inside the model server. The first phase reads your prompt; the second writes the answer one token at a time. They run on the same hardware but hit different limits, so they have different prices, different latency, and different levers. If you budget an agent run as "tokens times a price", you will be wrong in both directions: a 400K-token code-review context is expensive because of its input, and its prefill dominates the latency before the first token appears, while a 6K-token patch with heavy thinking looks cheap but spends most of its wall-clock time, and a large share of its bill, decoding output.

You already call the Messages API and read `usage`. This lesson gives you the model behind those numbers, so that `input_tokens`, `output_tokens`, `max_tokens` and `stop_reason` turn into a cost and latency forecast you can plan a pipeline around. The next two lessons build on it: lesson 02 explains what the server holds in memory between decode steps, lesson 03 shows how to stop paying for the same prefill twice.

## Core idea

A request goes through three stages. The tokenizer turns text into integer ids. Prefill runs the whole prompt through the network in one batched pass, producing the first output token and, as a side effect, the per-token key and value tensors that later steps need (the KV cache, the subject of lesson 02). Decode then generates one token per forward pass, appending each new token's keys and values to the cache, until the model emits an end-of-turn token, hits a stop sequence, or reaches `max_tokens`.

```
 prompt text
     |
 [tokenizer] -> N input ids
     |
 [prefill]   one pass over all N tokens        compute-bound, parallel
     |       -> first output token + KV cache  sets time to first token (TTFT)
     v
 [decode]    one pass per output token         memory-bandwidth-bound, sequential
   loop      reads all weights + KV cache      sets tokens per second (TPS)
     |       until end_turn / stop_sequence / max_tokens
     v
 response + usage{input_tokens, output_tokens}
```

Prefill is compute-bound. All N prompt tokens go through each weight matrix together, so every weight loaded from GPU memory is multiplied against thousands of vectors. The hardware's arithmetic units stay busy, and the time grows with N (and, for the attention part, faster than linearly, because every token attends to every earlier one). Decode is memory-bandwidth-bound. Each step produces one token per sequence, but it still has to stream every weight and the whole KV cache for that sequence from memory. Very little arithmetic happens per byte moved, so the arithmetic units wait on memory. Raschka's KV-cache chapter and the CS336 inference lectures (sources below) both cover this split; it is the standard account of transformer serving, and the reason serving systems such as vLLM batch many sequences' decode steps together.

The two latency numbers you can observe from the client map onto the two phases. Time to first token (TTFT) is queueing plus prefill of the uncached part of your prompt. Tokens per second (TPS) after that is the decode rate. End-to-end latency is roughly TTFT plus output tokens divided by TPS. Long prompts move TTFT; long outputs move everything after it. Thinking counts here: on Opus 5.5, adaptive thinking is always on and its tokens are billed as output tokens and count toward `max_tokens` (Steering thinking docs), so a request that "only" returns 300 visible tokens may have decoded several thousand.

## Mechanics

### What the price sheet is telling you

The pricing page lists Opus 5.5 at $4 per million input tokens and $20 per million output tokens (Claude pricing, checked 2026-10-17). Sonnet 5.5 is $2 / $10 and Haiku 5.5 is $0.10 / $0.50 for prompts up to 100,000 tokens, $0.50 / $2.50 above that (same page). The 5x output multiplier is consistent with the hardware story: a decoded token occupies a slot in a memory-bound step, a prefilled token shares a compute-bound pass with thousands of others. Anthropic does not publish its cost model, so treat that as the explanation the ratio is consistent with, not a disclosed formula.

The ratio changes which side of the bill dominates. Output cost exceeds input cost only when output is more than one fifth of input. Take one agent turn with a 50,000-token prompt and 2,000 output tokens on Opus 5.5: input is 50,000 x $4 / 1M = $0.20, output is 2,000 x $20 / 1M = $0.04. Now repeat that over a 10-turn tool loop where the prompt grows by about 3,000 tokens a turn. The loop re-sends the whole history every turn, so input is billed on roughly 50K + 53K + ... + 77K = 635,000 tokens ($2.54), while output is 20,000 tokens ($0.40). For agent loops, input dominates even at a 5x output price, which is exactly why prompt caching (lesson 03) is the first lever. For long single-shot generation, say a 30,000-token file from a 5,000-token spec, output dominates: $0.60 against $0.02.

Context length has its own costs. Opus 5.5 has a 1M-token context window and a 128K-token maximum output on the synchronous Messages API (Models overview). Opus 5.5 bills the full 1M window at standard rates; Haiku 5.5 is the exception with the 100K price step above (Claude pricing, "Long context pricing"). Tokens are not words: models from Claude Opus 4.7 onward use a tokenizer that produces about 30% more tokens for the same text than earlier models, and 1M tokens is roughly 555K English words on it (Claude pricing; Models overview). If you migrated a pipeline from a 4.6-era model and kept your token budgets, your budgets are now about 30% tight. Use the token counting endpoint on the model you actually call rather than a characters-per-token heuristic.

### `max_tokens` is a decode budget, not a target

`max_tokens` caps the decode loop: thinking plus visible text, combined (Steering thinking docs). When the loop hits it, the response comes back with `stop_reason: "max_tokens"` and whatever was produced so far. The full set of stop reasons is `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`, `pause_turn`, `refusal` and `model_context_window_exceeded`; the last one means the response filled the context window before reaching `max_tokens`, and the docs say to treat it as truncated too (Stop reasons and fallback).

Two numbers to keep in your head. This course defaults to 16,000 for non-streaming calls (the value the Steering thinking examples use) and 64,000 for streaming ones. The hard ceiling is 128K (Models overview). Between those, the Python SDK enforces a rule you may not have hit yet: with the default client timeout, a non-streaming `messages.create` computes an expected duration of `3600 s x max_tokens / 128,000` and raises `ValueError("Streaming is required for operations that may take longer than 10 minutes...")` before sending anything when that exceeds 600 s (anthropic 1.15.0, `_base_client.py`, `_calculate_nonstreaming_timeout`; the error links to the Python SDK "long requests" section). That puts the cutoff at `max_tokens` above 21,333. So a 64K budget forces you onto `messages.stream(...)`, and `stream.get_final_message()` gives you the same `Message` object with `stop_reason` and `usage` as a non-streaming call.

The sample below runs offline. It uses `cost_lab.transport.make_client` from the course exercise, which replays recorded responses from `course/m0-cost-lab/fixtures/` instead of calling the API: `loop_truncated` (a non-streaming reply cut off at `max_tokens`) and `stream_truncated` (an SSE stream with the same ending). Run it from the repository root with `PYTHONPATH=course/m0-cost-lab/starter/src:course/m0-cost-lab/lesson_support/src uv run --frozen python site/samples/m0/01-1.py`. With a real client (`anthropic.Anthropic()`) the same functions work unchanged.

Sample: `site/samples/m0/01-1.py`.

```python
from pathlib import Path

from cost_lab.transport import make_client

FIXTURES = Path("course/m0-cost-lab/fixtures")
USD_PER_MTOK = {"input": 4.00, "output": 20.00}
TRUNCATED = {"max_tokens", "model_context_window_exceeded"}


def cost_usd(usage) -> float:
    return (
        usage.input_tokens * USD_PER_MTOK["input"] + usage.output_tokens * USD_PER_MTOK["output"]
    ) / 1_000_000


def answer(client, prompt: str) -> str:
    response = client.messages.create(
        model="claude-opus-5-5",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    print(
        f"stop_reason={response.stop_reason} "
        f"in={response.usage.input_tokens} out={response.usage.output_tokens} "
        f"cost=${cost_usd(response.usage):.6f}"
    )
    if response.stop_reason in TRUNCATED:
        raise RuntimeError(f"truncated output, refusing to use it: {text!r}")
    return text


def long_answer(client, prompt: str) -> str:
    params = {
        "model": "claude-opus-5-5",
        "max_tokens": 64000,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        client.messages.create(**params)
    except ValueError as exc:
        print(f"non-streaming refused client-side: {str(exc).split('. ')[0]}")
    with client.messages.stream(**params) as stream:
        text = "".join(stream.text_stream)
        final = stream.get_final_message()
    print(f"streamed stop_reason={final.stop_reason} out={final.usage.output_tokens}")
    if final.stop_reason in TRUNCATED:
        raise RuntimeError(f"truncated output, refusing to use it: {text!r}")
    return text


client, transport = make_client(FIXTURES, ["loop_truncated", "stream_truncated"])
for call in (answer, long_answer):
    try:
        call(client, "Price and stock for item A1?")
    except RuntimeError as exc:
        print(exc)
print(f"requests that reached the transport: {len(transport.requests)}")
```

Output, run on 2026-10-17 against the synthetic fixtures:

```
stop_reason=max_tokens in=712 out=20 cost=$0.003248
truncated output, refusing to use it: 'A1 costs 12.50 and'
non-streaming refused client-side: Streaming is required for operations that may take longer than 10 minutes
streamed stop_reason=max_tokens out=9
truncated output, refusing to use it: 'A1 costs 12.50 and 7 are in stock'
requests that reached the transport: 2
```

Three things to read off it. The truncated reply parses as plausible text; only `stop_reason` tells you it is incomplete. The 64K non-streaming call never left the process: two fixtures, two requests, and the refused call is not one of them. And the streamed message carries the same `stop_reason` as a non-streaming one, so one truncation check covers both paths. The course exercise (stages `01-tool-loop` and `02-streaming`) makes you build this check into a tool loop and a streaming helper.

What to do on truncation depends on the task. For structured output, a truncated JSON document is garbage: raise `max_tokens` (and switch to streaming if you cross 21,333) or lower the effort level. For prose you can continue by appending the partial assistant turn and a new user message asking to continue, as the stop-reasons page shows. Either way, the decision belongs in code, not in whatever reads the text downstream.

## Pitfalls seen in the wild

- **Treating `max_tokens` as the expected length.** Teams set `max_tokens=128000` "to be safe" on a non-streaming call and get a `ValueError` from the SDK, or set it low to "save money" and get truncated JSON. You are billed for tokens generated, not for the cap. Size the cap for the worst legitimate output including thinking, and stream above 21,333.
- **Ignoring `stop_reason` because the text looks fine.** A truncated reply often ends mid-sentence but sometimes ends at a clean line break. The fix is a hard check on `max_tokens` and `model_context_window_exceeded` in every call path, streaming included, before the output reaches a parser or a commit.
- **Forgetting that thinking is output.** On Opus 5.5 thinking cannot be disabled and defaults to effort `medium` (Models overview); its tokens are billed at $20/MTok and count toward `max_tokens`. A cap sized for the visible answer alone truncates on hard inputs. Size for both, or lower effort for the step.
- **Budgeting agent loops by output.** Because output is 5x the price, people optimise response length while the history re-sent every turn is the real bill. Measure `input_tokens` per turn across a loop before deciding what to cut.
- **Carrying token budgets across model generations.** The tokenizer change at Opus 4.7 adds about 30% tokens for the same text (Claude pricing). Context-window guards and cost forecasts calibrated on an older model silently drift. Recount with the token counting endpoint on the target model.

## What interviewers ask

**Why is decode slower per token than prefill?**
Prefill pushes all prompt tokens through each weight matrix in one pass, so it is limited by arithmetic throughput and amortises each weight load over thousands of tokens. Decode produces one token per sequence per pass and must re-read the weights and that sequence's KV cache every step, so it is limited by memory bandwidth.

**A request has a 200K-token prompt and a 500-token answer. Where does the latency go, and where does the money go?**
Latency is mostly TTFT, because prefill of 200K uncached tokens dominates a 500-token decode. Money is also mostly input: on Opus 5.5, 200K x $4/MTok is $0.80 against 500 x $20/MTok, $0.01, so prompt caching is the lever for both.

**What does `stop_reason: "max_tokens"` mean and how do you handle it?**
The decode loop hit your cap and the content is incomplete, even if it looks finished. Handle it explicitly: raise the cap (streaming above the SDK's non-streaming limit), reduce effort, or continue the turn, and never pass the partial result to a parser as if it were complete.

**Why does the Python SDK refuse some non-streaming requests?**
With the default timeout it estimates duration as one hour per 128K output tokens and raises if that exceeds ten minutes, which happens above about 21,333 `max_tokens`. Long generations keep an HTTP connection open long enough for proxies and load balancers to cut it, so the SDK forces you onto streaming, where `get_final_message()` still returns a normal `Message`.

**How does context length affect cost and throughput beyond the per-token price?**
Longer prompts mean longer prefill (attention grows faster than linearly with length) and a larger KV cache that every decode step must read, so TTFT rises and the server fits fewer concurrent sequences. On Opus 5.5 the per-token price stays flat up to 1M tokens, so the cost shows up as latency and, on the provider side, as fewer requests per GPU.

## Sources

- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-10-17
- [Models overview](https://platform.claude.com/docs/en/models/overview), checked 2026-10-17
- [Stop reasons and fallback](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons), checked 2026-10-17
- [Steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost), checked 2026-10-17
- [Python SDK (long requests)](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python), checked 2026-10-17
- [Streaming messages](https://platform.claude.com/docs/en/build-with-claude/streaming), checked 2026-10-17
- [Raschka, LLMs from Scratch, KV cache bonus material](https://github.com/rasbt/LLMs-from-scratch/tree/main/ch04/03_kv-cache), checked 2026-10-17
- [Stanford CS336 Language Modeling from Scratch](https://cs336.stanford.edu/), checked 2026-10-17
- [vLLM documentation](https://docs.vllm.ai/en/stable/), checked 2026-10-17
