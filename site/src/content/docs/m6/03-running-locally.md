---
title: Running locally
description: Ollama and llama.cpp as OpenAI-compatible servers on a laptop, the defaults that change what you measure, how a streamed response looks on the wire and what counts as a token, why a reasoning model can return an empty answer, the course's live numbers for qwen3.5:0.8b and how far they can be read, and what a laptop proves about serving and what it does not.
module: m6
order: 3
verified_on: 2026-10-22
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "github:ollama/ollama": "v0.40.8"
  "model:default": claude-opus-5-5
sources:
  - url: https://docs.ollama.com/api/openai-compatibility
    title: Ollama, OpenAI compatibility
    checked: 2026-10-22
  - url: https://docs.ollama.com/faq
    title: Ollama FAQ
    checked: 2026-10-22
  - url: https://docs.ollama.com/capabilities/thinking
    title: Ollama, Thinking
    checked: 2026-10-22
  - url: https://ollama.com/library/qwen3.5:0.8b
    title: Ollama library, qwen3.5:0.8b
    checked: 2026-10-22
  - url: https://huggingface.co/Qwen/Qwen3.5-0.8B
    title: Qwen3.5-0.8B model card
    checked: 2026-10-22
  - url: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
    title: llama.cpp server README
    checked: 2026-10-22
---

**Prerequisites:** [M0 lesson 01](../../m0/01-tokens-prefill-decode/), which defines time to first token (TTFT) and decode speed, and stage 01 of the exercise, whose load generator this lesson points at a real model.

## Why this matters for the factory

Stages 01 and 05 run against a fake server because a test needs known answers. Before any of that code meets a vLLM deployment, it should meet a real model, and a laptop is the cheapest place to find one: no GPU bill, no cluster, and prompts that never leave the machine. Ollama and llama.cpp both serve an OpenAI-compatible endpoint, so the load generator and the gateway you wrote need a different base URL and nothing else.

That convenience has a trap. A laptop run produces TTFT and TPS numbers that look like a benchmark, and the course's own stage 02 record shows how easily they mislead. This lesson covers the two runtimes, the stream format your client has to parse, and how to read a local measurement without overclaiming.

## Core idea

Three servers, one wire format. vLLM, Ollama and llama.cpp's `llama-server` all accept `POST /v1/chat/completions` and stream server-sent events, so one client can drive them all. What differs sits around the protocol, and each difference can change a measurement or break a probe:

| | Ollama | llama.cpp `llama-server` |
| --- | --- | --- |
| Base URL | `http://localhost:11434/v1` | `http://localhost:9931/v1` (default port 9931) |
| Health probe | no `/health` (answers 404 in the course's runs) | `/health`: 503 while loading, then 200 |
| Parallel requests per model | `OLLAMA_NUM_PARALLEL`, default 1 | `-np`, default auto, continuous batching on |
| Default context | 4096 tokens | `-c 0`, "loaded from model" |
| Reasoning text in the response | `delta.reasoning` in the course's runs; `message.thinking` on `/api/chat` | `reasoning_content` with `--reasoning-format deepseek` |

The model you pull is also a packaging decision someone else made: a quantisation, a chat template, sometimes extra files. Your measurement is of that package on that runtime.

## Mechanics

### Ollama

Ollama's OpenAI compatibility page gives the base URL `http://localhost:11434/v1/` and one line that matters for client code: "The client requires an API key value, but Ollama ignores it." The supported request fields for chat completions include `stream`, `stream_options` with `include_usage`, `max_tokens`, `tools` and `reasoning_effort`, which is what stage 01's request needs.

Four defaults from the FAQ change what you measure:

- **Context.** "By default, Ollama uses a context window size of 4096 tokens." Set `OLLAMA_CONTEXT_LENGTH` before testing anything long.
- **Parallelism.** `OLLAMA_NUM_PARALLEL` is "The maximum number of parallel requests each model will process at the same time, default 1", and "Required RAM will scale by `OLLAMA_NUM_PARALLEL` * `OLLAMA_CONTEXT_LENGTH`". A load test at concurrency 2 against the defaults measures a queue as much as the model.
- **Queue.** `OLLAMA_MAX_QUEUE`, "The maximum number of requests Ollama will queue when busy before rejecting additional requests", defaults to 512.
- **Unloading.** "By default models are kept in memory for 5 minutes before being unloaded." The first request after an idle period pays for loading the weights.

Ollama has no `/health` route, which is why stages 05 and 08 probe `/` for the Ollama route.

What `ollama pull qwen3.5:0.8b` fetches is a bundle. The library page lists, at 1.3 GB in all, the model (752M parameters, quantisation `Q8_0`, 812 MB), a vision projector (101M parameters, BF16), a "draft" model (275M parameters, `Q8_0`) with `"draft_num_predict": 2` in its parameters, and the Apache 2.0 licence text. A draft model is the small model that speculative decoding uses to propose tokens for the main model to check. So the tag stage 02 pulled is, as the library lists it on 2026-10-22, an 8-bit GGUF build with a draft model attached, not the BF16 checkpoint on Hugging Face; a vLLM deployment of the same family would run a different file with different kernels.

### llama.cpp

`llama-server` serves the same endpoints from a GGUF file. `-hf <user>/<model>[:quant]` downloads from Hugging Face: "quant is optional, case-insensitive, default to Q4_K_M". The README gives "port to listen (default: 9931)". Three details from the README make it a good second runtime for testing a client:

- **Health that tells you about loading.** `GET /health` answers 503 with `"message": "Loading model"` while the weights load, then 200 with `{"status": "ok" }`. Stage 05's gateway probe works against it unchanged.
- **Real batching.** `-np, --parallel N` is the "number of server slots (default: -1, -1 = auto)", and `-cb, --cont-batching` is "whether to enable continuous batching (a.k.a dynamic batching) (default: enabled)". `--metrics` enables a Prometheus endpoint.
- **Server-side timings.** Responses carry a `timings` object with `prompt_n`, `prompt_ms`, `prompt_per_second`, `predicted_n`, `predicted_per_second` and `cache_n`, the "number of prompt tokens reused from cache". Comparing them with what your client measured separates network and queueing from model time.

For reasoning models, `--reasoning-format deepseek` "puts thoughts in `message.reasoning_content`" and `--reasoning-budget N` sets a "token budget for thinking: -1 for unrestricted, 0 for immediate end".

### The stream on the wire

Stage 01's rules for counting are the ones every client of these servers needs. A streamed chat completion is a series of `data: {json}` lines separated by blank lines, ending in `data: [DONE]`. An output token is a chunk whose `choices[*].delta.content` is non-empty. The first chunk usually carries only the role, a finish chunk carries `finish_reason` and an empty delta, and with `stream_options.include_usage` a final chunk has `choices: []` and the `usage` totals; none of them is a token. A stream that ends without `[DONE]` failed, however much text arrived.

The sample builds three invented streams, with arrival times in milliseconds after the request was sent: a normal answer, a reasoning model that spends its whole `max_tokens` budget thinking, and a connection cut after two chunks. The helper counts content tokens and reasoning chunks separately.

Sample: `site/samples/m6/03-1.py`.

```python
from serving_lab_lessons.streams import DONE, chunk, tally, usage_chunk

answer = [
    (212.0, chunk({"role": "assistant", "content": ""})),
    (240.0, chunk({"content": "Paged"})),
    (281.0, chunk({"content": " blocks"})),
    (322.0, chunk({"content": " hold"})),
    (363.0, chunk({"content": " the cache."})),
    (364.0, chunk({}, finish_reason="stop")),
    (365.0, usage_chunk(prompt_tokens=14, completion_tokens=4)),
    (365.5, DONE),
]
thinking = [(212.0, chunk({"role": "assistant", "content": ""}))]
thinking += [(240.0 + 41 * i, chunk({"reasoning": f" step{i}"})) for i in range(48)]
thinking += [
    (2170.0, chunk({"content": ""}, finish_reason="length")),
    (2171.0, usage_chunk(prompt_tokens=14, completion_tokens=48)),
    (2171.5, DONE),
]
cut = answer[:3]

for line in [answer[0][1], answer[1][1], answer[-1][1]]:
    print(line)
for name, arrivals in [("answer", answer), ("thinking", thinking), ("cut", cut)]:
    t = tally(arrivals)
    print(
        f"{name:<8} content={t.content_tokens} reasoning={t.reasoning_chunks} ttft={t.ttft_ms}"
        f" tps={t.tps and round(t.tps, 1)} finish={t.finish_reason}"
        f" usage={t.usage_completion_tokens} done={t.done} text={t.text!r}"
    )
```

Output, run on 2026-10-22:

```
data: {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": null}]}
data: {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": "Paged"}, "finish_reason": null}]}
data: [DONE]
answer   content=4 reasoning=0 ttft=240.0 tps=32.5 finish=stop usage=4 done=True text='Paged blocks hold the cache.'
thinking content=0 reasoning=48 ttft=None tps=None finish=length usage=48 done=True text=''
cut      content=2 reasoning=0 ttft=240.0 tps=48.8 finish=None usage=None done=False text='Paged blocks'
```

The answer's TTFT is 240 ms, the first chunk with text, not 212 ms, when the role-only chunk arrived; a client that starts its clock on the first byte reports a TTFT that is 28 ms too good here and far too good on a reasoning model. TPS uses stage 01's definition, four tokens over the 123 ms between the first and last token. In the thinking stream the server finished normally, `usage` reports 48 completion tokens, `finish_reason` is `length`, and there is no answer at all. The cut stream has text and a plausible TPS, and without `[DONE]` it is a failure, which is how stage 01 scores it.

### Reasoning models and the empty answer

That thinking stream is what stage 02 first got from `qwen3.5:0.8b` on Ollama. With default settings the model reasons first, its chunks arrive with `delta.reasoning` set and `delta.content` empty, and a 48-token `max_tokens` runs out before any answer starts, so no token counts and TTFT is `None`. The fix is a request field: stage 02 sends `{"reasoning_effort": "none"}` through `extra_body`, and stage 08 does the same for the gateway's local route. Ollama's compatibility page documents the mapping: for "Boolean-only models that support enabling thinking", recognised efforts map to `true`, "while `"none"` requests `false`". Ollama's own `/api/chat` returns the same split as `message.thinking` and `message.content`.

The default is a packaging choice. The Hugging Face chat template for Qwen3.5-0.8B opens a thinking block only when `enable_thinking` is true, while the course's Ollama run reasoned by default. Check what your runtime and model build do before you measure, and decide which TTFT you want: time to the first answer token is what a user waits for, while reasoning tokens cost decode time and count against `max_tokens` either way.

### The course's numbers, and how far they go

Stage 02 ran once for real on 2026-10-22 and committed an aggregate record. The sample reads it, derives what the aggregate allows, and puts it next to the local route's latencies from the stage 08 record of the same day.

Sample: `site/samples/m6/03-2.py`.

```python
from serving_lab_lessons.local_runs import local_route_latencies, local_run_summary

lab = "course/m6-serving-lab/fixtures/"
s = local_run_summary(lab + "live_local_model_run.json")
print(f"{s['model']} on {s['runtime']}, {s['machine_class']}")
print(f"{s['requests']} requests at concurrency {s['concurrency']}, max_tokens {s['max_tokens']}")
print(f"TTFT ms p50/p90/p99: {s['ttft_ms']['p50']} / {s['ttft_ms']['p90']} / {s['ttft_ms']['p99']}")
print(f"requests with TTFT >= p50: at least {s['at_or_above_p50']} of {s['requests']}")
print(f"output tokens ~{s['output_tokens']}, {s['tokens_per_request']:.1f} per request")
print(f"decode at p50 TPS {s['tps_p50']}: {s['decode_s_at_p50']:.2f} s per request")
print(f"TTFT p50 + decode: {s['ttft_plus_decode_s']:.2f} s")
print(
    f"wall {s['wall_s']} s over {s['rounds']} rounds of {s['concurrency']}: {s['seconds_per_round']:.2f} s per round"
)

stage08 = local_route_latencies(lab + "live_gateway_run.json")
print("stage 08 local answers, one at a time (ms, tokens):", stage08)
```

Output, run on 2026-10-22:

```
qwen3.5:0.8b on ollama, Apple Silicon, CPU/GPU shared
8 requests at concurrency 2, max_tokens 48
TTFT ms p50/p90/p99: 2281.5 / 2526.7 / 2526.7
requests with TTFT >= p50: at least 5 of 8
output tokens ~330, 41.2 per request
decode at p50 TPS 24.8: 1.66 s per request
TTFT p50 + decode: 3.94 s
wall 16.68 s over 4 rounds of 2: 4.17 s per round
stage 08 local answers, one at a time (ms, tokens): [(548.1, 31), (644.6, 31), (748.3, 44)]
```

The record says: eight requests, none failed, TTFT p50 2,281.5 ms and p90 2,526.7 ms, a median of 24.8 tokens per second per request, 19.8 output tokens per second overall. The stage asserted floors of a p50 TPS above 5 and a p90 TTFT under 10,000 ms, and both held. The run used Ollama 0.34.1; the daemon updated to 0.40.8 later that day, and the record does not log the runtime version.

Do not read 2.3 s as this model's TTFT on a warm laptop. The run sent no warm-up request, so if the model was not already in memory (Ollama unloads a model after five idle minutes by default), the first requests include loading the weights. Loading does not explain the whole figure, though. With nearest-rank percentiles over eight values, the p50 is the fourth-smallest TTFT, so at least five of the eight requests waited 2,281.5 ms or longer, and all of them at most 2,526.7 ms. The rough timing is consistent with every request paying about 2.3 s before its first token: TTFT plus decode at the median rate gives 3.94 s, close to the 4.17 s per pair of requests that the wall time implies. The stage 08 record points the same way from the other side: the same model, called one request at a time without streaming, returned whole answers of 31 to 44 tokens in 548 to 748 ms.

The record cannot say what made those 2.3 s. Candidates are the cold start, two requests sharing a runtime whose parallelism the record does not log (`OLLAMA_NUM_PARALLEL` defaults to 1), and the machine itself ("Apple Silicon, CPU/GPU shared" is the record's whole description). To separate them, send one warm-up request, run concurrency 1, then repeat at 2 with `OLLAMA_NUM_PARALLEL` set explicitly, and record the setting with the numbers. The same applies to the gap between 24.8 tokens per second per request at concurrency 2 and the stage 08 answers, which work out to roughly 48 to 59 tokens per second for a single request, prefill and HTTP included.

### What a laptop proves and what it does not

A local run is good evidence for:

- **Your client against a real server.** Role-only chunks, usage chunks, reasoning fields, a 404 on a probe, an empty answer: stage 02 found the reasoning problem against the real model, which no fake server would have shown.
- **Your routing and failure handling.** Stage 08 sent six prompts through the gateway, every one landed on its expected route, and the run cost 0.056779 USD, all of it on the three API calls.
- **Development without spend or data movement.** Prompts stay on the machine, which matters when the test data is real.

It is not evidence for:

- **Throughput on a GPU server.** vLLM's continuous batching and paged KV cache over HBM behave differently from a runtime with one slot on shared laptop memory. Lesson 05 measures that properly.
- **The model you will deploy.** An 8-bit GGUF with a draft model is not FP8 weights on an H100, and quality differences between quantisations are measured with your eval set, per deployment.
- **Long contexts or multi-tenant tail latency.** The 4096-token default and a handful of requests say nothing about either.
- **Cost per token.** A laptop has no hourly price to divide; lesson 05's cost model needs a GPU price and a run on the GPU.

## Common pitfalls

- **Measuring a cold model.** Send a warm-up request and discard it, or the first requests carry the load time. After five idle minutes Ollama unloads the model again.
- **Comparing concurrency levels without the runtime's parallel setting.** With `OLLAMA_NUM_PARALLEL` at 1, concurrency 2 measures a queue. Record the setting with every run.
- **Starting the TTFT clock on the first byte.** The role-only chunk arrives before any text. Count from the first non-empty `delta.content`.
- **Ignoring reasoning output.** A reasoning model can spend all of `max_tokens` thinking and return an empty `content` with a normal finish. Set the reasoning control explicitly, and check `content` before counting a request as answered.
- **Probing `/health` on Ollama.** It answers 404; probe `/` or `/v1/models`. llama.cpp's `/health` answers 503 until the model has loaded.
- **Testing long prompts at the default context.** Ollama's default window is 4096 tokens. Raise it before drawing conclusions about long inputs.
- **Putting laptop numbers in a capacity plan.** They describe one build on one machine. Plan with numbers from the hardware and engine you will run.

## What interviewers ask

**How do you test a client for a self-hosted model before you have GPUs?**
Against a fake server with known timings for unit tests, then against Ollama or `llama-server` on a laptop, which speak the same OpenAI-compatible API as vLLM. The local run catches protocol details the fake does not have, such as reasoning fields or a missing health route.

**A local benchmark shows a 2.3 s TTFT for a 0.8B model. What do you check?**
Whether there was a warm-up request (model load), the runtime's parallel setting against the test's concurrency (queueing), and where the clock starts and stops (first byte or first content token). Then rerun at concurrency 1, warm, and compare.

**An OpenAI-compatible call to a reasoning model returns an empty `content`. Why?**
The model spent its `max_tokens` on reasoning, which the server returns in a separate field (`reasoning` or `reasoning_content` depending on the runtime), so the answer never started. Disable or budget reasoning (`reasoning_effort: "none"` on Ollama, `--reasoning-budget` on `llama-server`), or raise `max_tokens`.

**What does a laptop benchmark tell you about production?**
That the client, the parsing and the routing work against a real model. Not throughput, tail latency, long-context behaviour or cost: those depend on the engine, the GPU, the quantised build and the concurrency you will actually run.

## Sources

- [Ollama, OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility), base URL, API key note, supported fields, `reasoning_effort` mapping, checked 2026-10-22
- [Ollama FAQ](https://docs.ollama.com/faq), context window, concurrent requests, keep-alive, checked 2026-10-22
- [Ollama, Thinking](https://docs.ollama.com/capabilities/thinking), checked 2026-10-22
- [Ollama library, qwen3.5:0.8b](https://ollama.com/library/qwen3.5:0.8b), the files in the bundle, checked 2026-10-22
- [Qwen3.5-0.8B model card](https://huggingface.co/Qwen/Qwen3.5-0.8B), the chat template's `enable_thinking` switch, checked 2026-10-22
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), `-hf`, `--port`, `-np`, `--cont-batching`, `--metrics`, `--reasoning-format`, `--reasoning-budget`, `/health` and `timings`, checked 2026-10-22
- Course code and records (repository files, not web sources): stages 01, 02, 05 and 08 in `course/m6-serving-lab/README.md`, the live records `course/m6-serving-lab/fixtures/live_local_model_run.json` and `live_gateway_run.json`, the lesson helpers `streams.py` and `local_runs.py` in `course/m6-serving-lab/lesson_support/src/serving_lab_lessons/`
