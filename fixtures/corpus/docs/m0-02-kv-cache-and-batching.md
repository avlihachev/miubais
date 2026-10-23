# KV cache and batching

**Prerequisites:** [lesson 01](../01-tokens-prefill-decode/), for the prefill and decode phases this lesson looks inside.

## Why this matters for the factory

Lesson 01 split a request into prefill and decode. This lesson is about the thing that connects them: the KV cache, the per-token state the server keeps in GPU memory so that each decode step does not recompute the whole prompt. Its size decides how many requests one GPU can serve at once, and that number, more than raw FLOPs, decides what inference costs to run. You do not see it in the Messages API, but you see its effects: long-context requests decode more slowly, and latency gets noisier under load. The Batch API's 50% discount and the low price of cached prefixes are consistent with KV memory being the scarce resource, but Anthropic does not publish its serving architecture, so treat that link as an inference, not a documented cause.

There are two reasons to know it cold. First, it lets you reason about provider behaviour from the outside, which is what the rest of M0 does with caching and batch. Second, the moment your factory runs an open-weight model for a classifier, an embedding step or a private code model (M6), these numbers become your capacity plan: how many concurrent agent sessions fit on a node, what a 128K context does to throughput, and which serving features you need.

## Core idea

Attention needs, for every earlier token, a key vector and a value vector at every layer. Recomputing them for the whole sequence at every decode step would make generation quadratic. So the server computes them once (during prefill for prompt tokens, during the step itself for each generated token) and stores them. That store is the KV cache, and its size per token is fixed by the architecture:

```
bytes per token = 2 (K and V) x layers x kv_heads x head_dim x bytes_per_value
```

The `kv_heads` term is why grouped-query attention (GQA) matters: many query heads share one key/value head, so the cache shrinks by the ratio of query heads to KV heads. `bytes_per_value` is 2 for bf16 and 1 for an fp8 KV cache. The formula is derived step by step in Raschka's KV-cache article and the CS336 inference lectures.

A worked example. Llama 3 70B has 80 layers, model dimension 8,192, 64 attention heads and 8 key/value heads (The Llama 3 Herd of Models, Table 3), so `head_dim` is 8,192 / 64 = 128. In bf16 that is 2 x 80 x 8 x 128 x 2 = 327,680 bytes, 320 KiB per token. The weights themselves are about 70 billion parameters x 2 bytes = 140 GB. Now the memory picture of one serving node:

```
 node HBM (illustrative: 8 accelerators x 80 GB = 640 GB)
 +-------------------+-----------+----------------------------------------+
 | weights  ~140 GB  | overheads | KV cache: everything else, ~400 GB     |
 +-------------------+-----------+----------------------------------------+
                                   shared by every in-flight sequence;
                                   one 128K-token sequence takes ~43 GB
```

Every in-flight sequence holds its own slice of the KV region for its whole lifetime. Decode is memory-bandwidth-bound (lesson 01), and a decode step for a batch of B sequences reads the weights once and each sequence's KV cache once. The weight read is shared by the batch, the KV read is not. Batching is how a server amortises the weight read; KV memory is what limits the batch. That is the whole economics of serving in two sentences, and every technique below either packs more sequences into the KV region or keeps the batch full.

## Mechanics

### The arithmetic, executed

The snippet below is plain Python with no model call, so it needs no fixture. It computes the per-token cache for the 70B example, how many sequences of a given length fit in a 400 GB KV budget, and how many bytes the node has to read from memory per generated token. The 640 GB node and 400 GB budget are illustrative assumptions, not a specific product; the architecture numbers come from the Llama 3 paper. Run it from the repository root with `uv run --frozen python site/samples/m0/02-1.py`.

Sample: `site/samples/m0/02-1.py`.

```python
from dataclasses import dataclass

GB = 1e9


@dataclass(frozen=True)
class Model:
    name: str
    layers: int
    kv_heads: int
    head_dim: int
    bytes_per_value: float

    @property
    def kv_bytes_per_token(self) -> float:
        return 2 * self.layers * self.kv_heads * self.head_dim * self.bytes_per_value


WEIGHTS_BYTES = 70e9 * 2
KV_BUDGET_BYTES = 400 * GB
MODELS = [
    Model("70B GQA, bf16 KV", 80, 8, 128, 2),
    Model("70B GQA, fp8 KV", 80, 8, 128, 1),
    Model("70B if MHA, bf16 KV", 80, 64, 128, 2),
]
CONTEXTS = [8_192, 32_768, 131_072, 1_000_000]


def bytes_read_per_token(model: Model, batch: int, context: int) -> float:
    # one decode step streams the weights once for the whole batch plus every sequence's own KV cache
    return WEIGHTS_BYTES / batch + context * model.kv_bytes_per_token


for m in MODELS:
    print(f"{m.name}: {m.kv_bytes_per_token / 1024:.0f} KiB per token")
    for ctx in CONTEXTS:
        per_seq = ctx * m.kv_bytes_per_token
        fits = int(KV_BUDGET_BYTES // per_seq)
        print(f"  {ctx:>9,} tokens: {per_seq / GB:7.1f} GB per sequence, {fits:4d} fit in 400 GB")

base = MODELS[0]
print("bytes read per generated token, 70B GQA bf16:")
for batch, ctx in [(1, 8_192), (64, 8_192), (9, 131_072)]:
    print(
        f"  batch {batch:>3}, context {ctx:>7,}: {bytes_read_per_token(base, batch, ctx) / GB:6.1f} GB"
    )
```

Output, run on 2026-10-17:

```
70B GQA, bf16 KV: 320 KiB per token
      8,192 tokens:     2.7 GB per sequence,  149 fit in 400 GB
     32,768 tokens:    10.7 GB per sequence,   37 fit in 400 GB
    131,072 tokens:    42.9 GB per sequence,    9 fit in 400 GB
  1,000,000 tokens:   327.7 GB per sequence,    1 fit in 400 GB
70B GQA, fp8 KV: 160 KiB per token
      8,192 tokens:     1.3 GB per sequence,  298 fit in 400 GB
     32,768 tokens:     5.4 GB per sequence,   74 fit in 400 GB
    131,072 tokens:    21.5 GB per sequence,   18 fit in 400 GB
  1,000,000 tokens:   163.8 GB per sequence,    2 fit in 400 GB
70B if MHA, bf16 KV: 2560 KiB per token
      8,192 tokens:    21.5 GB per sequence,   18 fit in 400 GB
     32,768 tokens:    85.9 GB per sequence,    4 fit in 400 GB
    131,072 tokens:   343.6 GB per sequence,    1 fit in 400 GB
  1,000,000 tokens:  2621.4 GB per sequence,    0 fit in 400 GB
bytes read per generated token, 70B GQA bf16:
  batch   1, context   8,192:  142.7 GB
  batch  64, context   8,192:    4.9 GB
  batch   9, context 131,072:   58.5 GB
```

Read the last block carefully, because it is why long contexts reduce throughput. At 8K tokens, going from batch 1 to batch 64 cuts memory traffic per generated token from 142.7 GB to 4.9 GB, a 29x gain, because the 140 GB weight read is shared. At 128K tokens only 9 sequences fit, and each one's own 42.9 GB cache must be read on every step, so the node moves 58.5 GB per token: about 12x worse than the 8K batched case. Capacity drops (149 sequences to 9) and per-token cost rises at the same time. GQA is what makes long context feasible at all: the same model with one KV head per query head would not fit a single 1M-token sequence in the budget. An fp8 KV cache doubles capacity at some accuracy risk.

From the API side you see this only through prices and latency. Opus 5.5 bills its full 1M context at standard per-token rates, while Haiku 5.5 charges $0.50 / $2.50 per MTok above 100K prompt tokens instead of $0.10 / $0.50 (Claude pricing). Whatever the provider's reasons for each price, the arithmetic above is why long-context requests are expensive to serve, and why decode TPS on very long contexts is lower even when the per-token price is flat. Anthropic does not publish its serving architecture; the numbers here describe an open-weight 70B model and are for building intuition, not for reverse-engineering Claude.

### Continuous batching

Before 2022, servers batched at the request level: a batch started together and finished when its longest sequence finished. Short requests sat idle in their slots, and new arrivals waited for the whole batch. Orca (OSDI 2022) introduced iteration-level scheduling: the scheduler runs one decode iteration at a time, so a finished sequence leaves the batch immediately and a waiting request joins at the next iteration. vLLM builds on the same iteration-level scheduling. The effect is that the batch stays full under mixed lengths, which is the condition the bytes-per-token arithmetic needs.

Continuous batching has a cost you will notice as an API user: your request shares each step with whoever else is in the batch. Prefill of a large new prompt competes with decode of running ones. vLLM's answer is chunked prefill, which splits large prefills into chunks and batches them with decode requests, prioritising decode; the vLLM optimisation guide describes it as balancing compute-bound prefill and memory-bound decode, and it is on by default in vLLM V1. That is one reason TTFT and TPS vary with load on any shared endpoint.

### Paged attention

Continuous batching keeps the batch full only if memory allocation keeps up. Early servers reserved a contiguous region per sequence sized for its maximum length, wasting most of it on sequences that stopped early and fragmenting the rest. PagedAttention (Kwon et al., SOSP 2023) stores the KV cache in fixed-size blocks and gives each sequence a block table, the same way an operating system maps virtual pages to physical frames. The paper reports near-zero KV memory waste and 2-4x throughput over FasterTransformer and Orca at the same latency, with larger gains for longer sequences and larger models.

Blocks also make sharing cheap. Two sequences with the same prefix can point at the same physical blocks. vLLM's automatic prefix caching hashes each full block together with its parent block's hash and the block's exact token ids (vLLM design, Automatic Prefix Caching), so a block is reusable only when everything before it is identical too. Hold on to that rule: it is exact-prefix matching, and it is the same contract the Claude API exposes as prompt caching in lesson 03.

When the KV region runs out anyway, vLLM preempts a running sequence and recomputes it later; the optimisation guide's remedies are to raise `gpu_memory_utilization`, lower `max_num_seqs` or `max_num_batched_tokens`, or add tensor parallelism. Those four knobs are your capacity plan when you self-host.

### Disaggregated prefill and decode

Prefill and decode want different hardware configurations: prefill wants compute and benefits from large batched matrix multiplies; decode wants memory bandwidth and KV capacity. Running both on the same GPUs means a burst of long prompts stalls everyone's decode. DistServe (OSDI 2024) assigns the two phases to different GPUs, tuned to separate TTFT and time-per-output-token targets, and reports serving 7.4x more requests within both latency constraints than colocated systems. llm-d, a CNCF Sandbox project for Kubernetes-native distributed inference, builds this in: its router selects a prefill endpoint and a decode endpoint for each request and coordinates the KV-cache transfer between them, alongside prefix-cache-aware routing and tiered KV offloading (llm-d architecture). That is where open serving stacks point in 2026: KV cache as a cluster-level resource that is routed, transferred and tiered, not a per-GPU detail.

## Pitfalls seen in the wild

- **Sizing a self-hosted node by weights alone.** "The model is 140 GB, we have 640 GB, plenty of room" ignores that one 128K-token conversation takes about 43 GB of cache. Size by concurrent sessions x expected context x per-token KV, and cap `max_model_len` to what your workload needs.
- **Giving every agent the maximum context "just in case".** Long histories shrink the batch and multiply per-token memory traffic. On an API that shows up as slower decode; on your own GPUs as fewer sessions. Trim, compact or summarise histories before they grow past what the task needs.
- **Benchmarking at batch 1.** Single-request latency tests measure the weight-read bound and say nothing about throughput under load. Load-test with realistic concurrency and context lengths, and watch preemption counts in vLLM's logs.
- **Mixing very long and very short requests on one deployment without chunked prefill or disaggregation.** A few 200K-token prefills stall interactive decode for everyone. Keep chunked prefill on, route long-context work to a separate pool, or use disaggregated serving.
- **Assuming prefix sharing tolerates small differences.** Block hashes chain through every earlier token, so a timestamp in the first block makes every later block unique. The fix is prompt layout, covered in lesson 03.

## What interviewers ask

**How big is the KV cache for a 70B model at 128K tokens?**
Per token it is 2 x layers x kv_heads x head_dim x bytes; for Llama 3 70B with 8 KV heads in bf16 that is 320 KiB, so a 128K-token sequence needs about 43 GB. Without GQA it would be eight times that, which is why GQA is close to mandatory for long context.

**Why does batching improve throughput for decode but not much for prefill?**
Decode is memory-bound: each step reads all weights for one token per sequence, so sharing that read across a batch divides its cost. Prefill already processes thousands of tokens per weight read and is compute-bound, so it is efficient even for a single request.

**What problem does PagedAttention solve?**
Contiguous per-sequence KV allocation wastes memory on reserved-but-unused space and fragmentation, which caps batch size. Paging the cache into fixed blocks with a per-sequence block table removes most of that waste and allows sharing blocks between sequences with a common prefix.

**What is continuous batching?**
Scheduling at the granularity of one decode iteration instead of one request, introduced by Orca: finished sequences leave and new ones join between steps. It keeps the batch full when output lengths vary, which is always.

**Why disaggregate prefill and decode?**
The phases have different bottlenecks and latency targets, and colocating them lets long prefills interfere with decode. Separate pools can be sized and parallelised for each phase, at the cost of moving the KV cache between them, which is what DistServe and llm-d's router manage.

## Sources

- [Kwon et al., Efficient Memory Management for Large Language Model Serving with PagedAttention (SOSP 2023)](https://arxiv.org/abs/2309.06180), published 2023-09-12, checked 2026-10-17
- [vLLM design, Paged Attention](https://docs.vllm.ai/en/stable/design/paged_attention/), checked 2026-10-17
- [vLLM design, Automatic Prefix Caching](https://docs.vllm.ai/en/stable/design/prefix_caching/), checked 2026-10-17
- [vLLM, Optimization and Tuning](https://docs.vllm.ai/en/stable/configuration/optimization/), checked 2026-10-17
- [Yu et al., Orca, A Distributed Serving System for Transformer-Based Generative Models (OSDI 2022)](https://www.usenix.org/conference/osdi22/presentation/yu), checked 2026-10-17
- [Zhong et al., DistServe, Disaggregating Prefill and Decoding for Goodput-optimized LLM Serving (OSDI 2024)](https://arxiv.org/abs/2401.09670), published 2024-01-18, checked 2026-10-17
- [llm-d architecture](https://llm-d.ai/docs/architecture), checked 2026-10-17
- [Llama Team, The Llama 3 Herd of Models](https://arxiv.org/abs/2407.21783), published 2024-07-31, checked 2026-10-17
- [Raschka, Understanding and Coding the KV Cache in LLMs from Scratch](https://magazine.sebastianraschka.com/p/coding-the-kv-cache-in-llms), published 2025-06-17, checked 2026-10-17
- [Stanford CS336 Language Modeling from Scratch](https://cs336.stanford.edu/), checked 2026-10-17
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-10-17
