---
title: Reranking and MMR
description: Two-stage retrieval with a recall-oriented candidate pool and a precision-oriented reranker, the pool arithmetic (150 to 20 in Anthropic's setup, 50 to 10 in the course), bi-encoders against cross-encoders, a BM25 reranker over the candidates, MMR for near-duplicate chunks, and the deltas the course measured with hashing and with local models.
module: m4
order: 4
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:fastembed": "0.9.0"
  "pypi:pgvector": "0.5.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://www.anthropic.com/engineering/contextual-retrieval
    title: Introducing Contextual Retrieval
    published: 2024-09-19
    checked: 2026-10-17
  - url: https://github.com/qdrant/fastembed
    title: FastEmbed README
    checked: 2026-10-17
  - url: https://platform.claude.com/docs/en/build-with-claude/embeddings
    title: Embeddings
    checked: 2026-10-17
  - url: https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf
    title: The use of MMR, diversity-based reranking for reordering documents and producing summaries
    published: 1998-08-01
    checked: 2026-10-17
  - url: https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf
    title: "The Probabilistic Relevance Framework: BM25 and Beyond"
    published: 2009-01-01
    checked: 2026-10-17
---

**Prerequisites:** [lesson 03](../03-hybrid-search/), which produces the fused candidate list this lesson reorders.

## Why this matters for the factory

Hybrid search is good at getting the right chunk somewhere into the top 50 and much worse at putting it in the top 10. On the course's golden set with the hashing embedder, fused recall is 0.792 at 50 and 0.656 at 10. With the bge-small embedder from the live stage the gap has the same shape: 0.875 at 50, 0.740 at 10. The model only sees the top few. Everything between rank 11 and rank 50 is retrieved and wasted.

Reranking closes part of that gap with a slower, more careful scorer that only runs on the candidates. In Anthropic's contextual retrieval experiments, adding a reranker took the cut in top-20 retrieval failures from 49% to 67%. Then a second problem appears: with overlapping chunks, the top 10 can hold the same paragraph twice, and every duplicate pushes a different useful chunk out of the prompt. MMR addresses that.

## Core idea

Split retrieval into stages with different jobs.

1. **Recall stage.** Cheap retrievers (lesson 03) produce a generous candidate pool. Its only job is to contain the answer. Its recall at the pool size is the ceiling for everything after it.
2. **Precision stage.** A reranker scores every candidate against the query, reading both together, and reorders the pool. It can only promote what the pool already has.
3. **Diversity stage.** MMR walks down the reranked list and skips candidates too similar to what it already picked.
4. **Cut.** The first k go into the prompt.

The pool size is the knob between them: larger pools raise the ceiling and cost reranker time on every query.

## Mechanics

### Candidate pool arithmetic

Anthropic's setup: "Perform initial retrieval to get the top potentially relevant chunks (we used the top 150)", rerank, "then select the top-K chunks (we used the top 20)". On the output size they report: "We tried delivering 5, 10, and 20 chunks, and found using 20 to be the most performant of these options." That is a pool 7.5 times the output.

The course uses 50 and 10: the fused top 50 (vector top 50 and full-text top 50 combined by RRF, cut at 50), reranked, then MMR down to 10. Five times the output. The arithmetic of cost is per query and linear in the pool: the live stage cross-encoded 48 queries × 50 candidates = 2,400 query-chunk pairs, which took 80 seconds on a shared CPU, about two seconds per query. At Anthropic's 150 that would be three times as much. Anthropic names the trade directly: "Because reranking adds an extra step at runtime, it inevitably adds a small amount of latency", and "There is an inherent trade-off between reranking more chunks for better performance vs. reranking fewer".

Stage 05 asserts the hashing pipeline's fused recall@50 of 0.792, and the README states the consequence: no reranker over that pool can reach recall@10 above 0.792, so the course's original 0.80 target was unreachable and the floor is 0.70. In the live run, the pool holds 0.875 and the cross-encoder lifts recall@10 to 0.781: of the 0.219 of recall still missing at 10, 0.094 was in the pool and the reranker did not promote it far enough, and 0.125 was never in the pool.

### Bi-encoders and cross-encoders

An embedding model is a bi-encoder: it encodes the query and each chunk separately, so chunk vectors can be computed once at indexing time and compared with a dot product. A cross-encoder reads the query and the chunk together and outputs one relevance score. It sees which words of the query match which words of the passage and in what context, so it ranks better, and none of its work can be precomputed, because every score depends on the query. That is why it runs on 50 candidates and not on 685 chunks.

fastembed ships one: `from fastembed.rerank.cross_encoder import TextCrossEncoder`, then `TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")` and `list(encoder.rerank(query, documents))` for one score per document. The exercise's `CrossEncoderReranker` wraps it behind the same `rerank(query, chunks, top_k)` interface as the offline reranker and imports fastembed only when it ranks a non-empty list. The model was a 91 MB download. Hosted options exist too: Anthropic ran its tests "with the Cohere reranker", and the Claude embeddings page lists Voyage's `rerank-3` and `rerank-3-lite`.

The scores are logits, not probabilities. Their scale is the model's, which matters in lesson 06: a support floor tuned for one reranker means nothing for another.

### A BM25 reranker for the offline stages

Stages 04 to 07 run without models, so the exercise's offline reranker is BM25 (Robertson and Zaragoza's probabilistic relevance framework) computed over the candidate set it is given. For a query term with document frequency `df` among `N` candidates, `idf = ln(1 + (N - df + 0.5) / (df + 0.5))`, and a chunk of `L` words scores `Σ idf · tf · (k1 + 1) / (tf + k1 · (1 - b + b · L / avg))` with `k1 = 1.2` and `b = 0.75`. Computing `idf` over the 50 candidates rather than the whole corpus makes a term rare when it is rare among the plausible answers, which is the distinction a reranker needs. It is still lexical: it cannot help a conceptual query whose answer shares no words with it.

### What reranking bought, measured

The hashing pipeline on the 48 golden queries at k = 10, pinned in the stage 05 tests within 0.02:

| pipeline | recall@10 | MRR | nDCG@10 |
| --- | --- | --- | --- |
| hybrid (RRF) | 0.656 | 0.406 | 0.468 |
| + lexical rerank | 0.750 | 0.545 | 0.595 |
| + MMR (λ 0.7) | 0.729 | 0.536 | 0.583 |

Recall@10 rises by 0.094 and MRR by 0.139: the reranker both pulls answers into the top 10 and moves them up within it. The live run with real models, read from the committed record:

Sample: `site/samples/m4/04-2.py`.

```python
from pathlib import Path

from retrieval_lab_lessons import live_models_summary

live = live_models_summary(Path("course/m4-retrieval-lab/fixtures/live_local_models_run.json"))
print(f"{live['embedder']} + {live['reranker']}")
print(f"{live['chunks']} chunks, {live['queries']} queries, k={live['k']}, pool {live['pool']}")
for name in ("hybrid", "reranked"):
    row = live[name]
    print(f"  {name:<9}" + "".join(f" {m} {row[m]:.3f}" for m in ("recall", "mrr", "ndcg")))
for kind, (before, after) in live["recall_by_kind"].items():
    print(f"  recall@10 {kind:<10} {before:.3f} -> {after:.3f}")
print(f"pool recall@50 {live['pool_recall']:.3f}")
print(f"index {live['index_seconds']:.0f} s, rerank eval {live['rerank_seconds']:.0f} s")
```

Output, run on 2026-10-23:

```
BAAI/bge-small-en-v1.5 + Xenova/ms-marco-MiniLM-L-6-v2
653 chunks, 48 queries, k=10, pool 50
  hybrid    recall 0.740 mrr 0.552 ndcg 0.598
  reranked  recall 0.781 mrr 0.648 ndcg 0.674
  recall@10 conceptual 0.312 -> 0.438
  recall@10 factual    0.938 -> 1.000
  recall@10 lexical    0.969 -> 0.906
pool recall@50 0.875
index 50 s, rerank eval 80 s
```

The cross-encoder's gain is mostly in ordering (MRR +0.096) and mostly, for recall, in the conceptual queries, the only kind where it can read past missing shared words. Lexical and factual recall barely move. (The record keeps the rerank time as 79.5 seconds; the sample rounds it.) The course's original target here was recall@10 of 0.85. The measured 0.781 misses it, so the live floor is the measurement rounded down, 0.75. The reason is the conceptual queries: they paraphrase without the document's words, and even the cross-encoder lifted only part of them from the pool.

### MMR

Maximal marginal relevance comes from Carbonell and Goldstein's 1998 SIGIR paper: "a document has high marginal relevance if it is both relevant to the query and contains minimal similarity to previously selected documents." It picks results one at a time. The exercise's `rerank.mmr` each time takes the candidate that maximises

```
λ · relevance(c) − (1 − λ) · max over picked p of similarity(c, p)
```

The first pick is the most relevant candidate. After that, a candidate pays for resembling anything already chosen. In the exercise, relevance is the reranker score scaled into zero to one (divided by the maximum when no score is negative, min-max otherwise), similarity is the cosine of the stored embeddings, and λ is 0.7.

Sample: `site/samples/m4/04-1.py`.

```python
import numpy as np
from retrieval_lab_lessons import toy_mmr

names = ["setup A", "setup A (overlap)", "pricing", "limits"]
relevance = [1.0, 0.97, 0.80, 0.60]
vectors = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.98, 0.2, 0.0],
        [0.3, 0.9, 0.1],
        [0.2, 0.1, 0.95],
    ]
)
for lam in (1.0, 0.7, 0.3):
    order = toy_mmr(relevance, vectors, lam=lam, top_k=3)
    print(f"lambda {lam}: {[names[i] for i in order]}")
```

Output, run on 2026-10-17:

```
lambda 1.0: ['setup A', 'setup A (overlap)', 'pricing']
lambda 0.7: ['setup A', 'pricing', 'setup A (overlap)']
lambda 0.3: ['setup A', 'limits', 'pricing']
```

At λ = 1.0, MMR is plain ranking and the near-duplicate (two chunks that share most of a paragraph, as overlap produces) takes second place. At 0.7 the duplicate drops behind "pricing". At 0.3 diversity dominates and the least relevant chunk, "limits", jumps to second because it is the most different. The stage 04 tests check the middle case on real chunks: two chunks sharing two of three paragraphs, where λ = 0.7 drops the second and λ = 1.0 keeps it.

On the golden set MMR costs a little: MRR 0.545 to 0.536, nDCG 0.595 to 0.583, recall down by one query. Each golden query has one anchor, so diversity cannot add a second relevant chunk there; it can only occasionally demote one. The payoff is in the prompt: fewer repeated paragraphs, more distinct sources per token. Measure it with a metric that rewards coverage if your questions need several passages.

## Common pitfalls

- **Reranking only the top 10.** A reranker reorders; it cannot add recall that is not in its input. Give it a pool several times the output.
- **A pool sized by habit.** Each candidate is a cross-encoder call on every query. Measure pool recall at several sizes and stop where it flattens.
- **Treating reranker scores as probabilities.** Cross-encoder logits and BM25 scores are on their own scales; any threshold on them is specific to that model.
- **MMR with a low λ.** Diversity at 0.3 promotes irrelevant chunks just for being different. Start near 0.7 and check MRR does not drop.
- **No per-kind breakdown.** The live reranker moved only conceptual recall. An overall average would hide where it helped and where it did nothing.

## What interviewers ask

**Why rerank at all if you already have hybrid search?**
First-stage retrievers optimise recall cheaply; their top 10 is noisy. A cross-encoder reads query and chunk together and ranks better, but cannot be precomputed, so it runs on a pool. In the course, reranking the fused top 50 raised recall@10 from 0.656 to 0.750 and MRR from 0.406 to 0.545 with a BM25 reranker; with real models MRR went from 0.552 to 0.648.

**How do you choose the candidate pool size?**
By the recall of the pool at that size and the reranker's latency per candidate. Anthropic retrieved 150 and kept 20; the course keeps 10 of 50, where the pool holds the answer for 0.875 of queries with bge-small. The pool's recall is the ceiling; past the point where it flattens, extra candidates only add latency.

**What is the difference between a bi-encoder and a cross-encoder?**
A bi-encoder embeds query and document separately, so documents are embedded once and compared by dot product: fast, indexable, less precise. A cross-encoder scores the pair jointly: more precise, nothing precomputable, so it is used only on a short list.

**What does MMR do and when does it hurt?**
It picks greedily by λ times relevance minus (1 − λ) times the highest similarity to anything already picked, removing near-duplicates from the top k. It hurts when every relevant chunk looks alike, or with λ too low; in the course at λ 0.7 it cost 0.001 MRR and freed slots taken by overlapping chunks.

## Sources

- [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval), Anthropic, 2024-09-19, the reranking section and the failure-rate results, checked 2026-10-17
- [FastEmbed README](https://github.com/qdrant/fastembed), version 0.9.0, the `TextCrossEncoder` example, checked 2026-10-17
- [Embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings), Claude docs, the reranker table, checked 2026-10-17
- Jaime Carbonell, Jade Goldstein, [The use of MMR, diversity-based reranking for reordering documents and producing summaries](https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf), SIGIR 1998, pages 335 to 336, DOI 10.1145/290941.291025 (authors' PDF), checked 2026-10-17
- Stephen Robertson, Hugo Zaragoza, [The Probabilistic Relevance Framework: BM25 and Beyond](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf), Foundations and Trends in Information Retrieval 3(4), 2009, pages 333 to 389, DOI 10.1561/1500000019 (author's PDF), checked 2026-10-17
- Course code (repository files, not web sources): stages 04, 05 and 08 in `course/m4-retrieval-lab/README.md` and their tests, the live record `course/m4-retrieval-lab/fixtures/live_local_models_run.json`, the lesson helpers in `course/m4-retrieval-lab/lesson_support/src/retrieval_lab_lessons/`
