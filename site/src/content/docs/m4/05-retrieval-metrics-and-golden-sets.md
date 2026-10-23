---
title: Retrieval metrics and golden sets
description: Recall@k, precision@k, MRR and nDCG@k defined and worked by hand, why the ideal DCG runs over min(k, relevant), how the course's golden set makes relevance deterministic with anchor phrases, what the numbers by query kind show, and the five-way failure taxonomy of the stage 07 error analysis.
module: m4
order: 5
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:fastembed": "0.9.0"
  "pypi:pgvector": "0.5.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://hamel.dev/blog/posts/evals-faq/
    title: "AI Evals: Everything You Need to Know"
    published: 2026-09-18
    checked: 2026-10-17
  - url: https://doi.org/10.1145/582415.582418
    title: Cumulated gain-based evaluation of IR techniques
    published: 2002-10-01
    checked: 2026-10-17
  - url: https://www.anthropic.com/engineering/contextual-retrieval
    title: Introducing Contextual Retrieval
    published: 2024-09-19
    checked: 2026-10-17
---

**Prerequisites:** [lesson 04](../04-reranking-and-mmr/), whose pipeline this lesson measures.

## Why this matters for the factory

When a retrieval-backed assistant gives a wrong answer, there are two very different causes. Either the chunk with the answer never reached the prompt, or it did and the model misread it, ignored it or made something up. The fixes have nothing in common: one is chunking, search and reranking, the other is prompting and model choice. If you only measure final answers, you cannot tell them apart.

Hamel Husain and Shreya Shankar's evals FAQ puts the order as: "debug retrieval first using IR metrics, then tackle generation quality using properly validated LLM judges." Retrieval is a search problem, and search has had well-defined metrics for decades. They need a set of questions with known answers in the corpus. This lesson builds both, using the course's golden set and the metrics stage 05 implements.

## Core idea

A golden set is a list of queries, each with the passages that answer it. Run the retriever on every query, look at the ranked list it returns, and score the list against the known answers at a cut-off k (the number of chunks that would go into the prompt).

- **Recall@k**: of all relevant chunks, how many are in the top k. The FAQ: "of all relevant documents, how many did you retrieve in the top k?" The primary number for retrieval feeding a model: a chunk outside the top k does not exist for the model.
- **Precision@k**: of the k chunks retrieved, how many are relevant. It measures how much of the prompt is noise.
- **MRR**: the mean over queries of 1 / rank of the first relevant chunk (0 when none is in the top k). The FAQ: "how high up was the first relevant document?"
- **nDCG@k**: discounted cumulative gain, normalised. Each relevant chunk at rank i contributes 1 / log2(i + 1), so rank 1 counts 1.0, rank 3 counts 0.5, rank 10 about 0.29; the sum is divided by the best possible sum for that query. From Järvelin and Kekäläinen's cumulated-gain measures (ACM TOIS, 2002); the course uses binary gains, relevant or not.

Average each over the queries, overall and per query kind.

## Mechanics

### Worked by hand

An invented query has three relevant chunks, `d1`, `d2` and `d5`. The retriever returns five: `d3, d8, d1, d6, d2`. Take k = 5.

- Recall@5: two of the three relevant chunks are in the list, 2/3 = 0.667.
- Precision@5: two of the five returned are relevant, 2/5 = 0.400.
- Reciprocal rank: the first relevant chunk is at rank 3, 1/3 = 0.333.
- DCG@5: relevant at ranks 3 and 5, so 1/log2(4) + 1/log2(6) = 0.5 + 0.3869 = 0.8869.
- Ideal DCG: the best list puts the relevant chunks at ranks 1, 2 and 3. There are only three, so the ideal has three terms: 1 + 0.6309 + 0.5 = 2.1309.
- nDCG@5: 0.8869 / 2.1309 = 0.4162.

The sample computes the same numbers with the lesson helpers, plus two that matter for the implementation.

Sample: `site/samples/m4/05-1.py`.

```python
from retrieval_lab_lessons import (
    dcg_at_k,
    ideal_dcg,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

ranked = ["d3", "d8", "d1", "d6", "d2"]
relevant = {"d1", "d2", "d5"}
k = 5
print(f"recall@{k}    {recall_at_k(ranked, relevant, k):.3f}")
print(f"precision@{k} {precision_at_k(ranked, relevant, k):.3f}")
print(f"RR          {reciprocal_rank(ranked, relevant):.3f}")
dcg = dcg_at_k(ranked, relevant, k)
print(f"DCG@{k}       {dcg:.4f}")
print(
    f"IDCG over min(k, relevant)=3: {ideal_dcg(3):.4f} -> nDCG {ndcg_at_k(ranked, relevant, k):.4f}"
)
print(f"IDCG over k=5 (wrong):        {ideal_dcg(5):.4f} -> {dcg / ideal_dcg(5):.4f}")
print("one relevant item at rank 1, k=10:", ndcg_at_k(["d1", "x"], {"d1"}, 10))
print(f"  with the ideal over k=10: {1 / ideal_dcg(10):.4f}")
```

Output, run on 2026-10-17:

```
recall@5    0.667
precision@5 0.400
RR          0.333
DCG@5       0.8869
IDCG over min(k, relevant)=3: 2.1309 -> nDCG 0.4162
IDCG over k=5 (wrong):        2.9485 -> 0.3008
one relevant item at rank 1, k=10: 1.0
  with the ideal over k=10: 0.2201
```

The ideal is the best ranking *this query* allows. With three relevant chunks, no retriever can put a relevant chunk at ranks 4 and 5, so the ideal stops at three terms, `min(k, relevant)`. Computing it over k terms is a silent bug: every score shrinks, nothing crashes. The last two lines show how badly. A query with one relevant chunk, retrieved at rank 1, is a perfect result and must score 1.0; with the ideal over k = 10 it scores 0.2201, and a perfect retriever would look like a poor one. Stage 05's tests pin exactly this case.

### The precision ceiling

Each golden query in the course has one anchor, and with overlapping chunks one or two chunks contain it. Precision@10 can therefore never exceed about 0.1 to 0.2, and the reference measures 0.077. Report precision when queries have many relevant passages; for single-answer questions, recall@k and MRR say more.

### A golden set with anchors

The FAQ's recipe for building one: generate it "by taking documents from your corpus, extracting key facts", "then generating questions those facts would answer." The course's set follows that shape by hand: 48 queries over the 32-document corpus (36 over course documents, 12 over the stories), 16 of each kind:

- `factual`: asks for a specific fact stated in the passage.
- `lexical`: contains an identifier or rare term that appears verbatim in the passage.
- `conceptual`: paraphrases the idea without sharing content words with the passage.

Each query carries an `anchor`, a 6 to 20 word verbatim phrase from one paragraph that occurs exactly once in its document. A chunk is relevant when it belongs to the query's document and its text contains the anchor, case-insensitive and whitespace-normalised. That makes relevance deterministic: no human labels per chunk, no model judging relevance, the same answer on every run. It also survives re-chunking. Change `max_chars` or overlap and the set of relevant chunks is recomputed from the anchor, so you can compare chunkers on the same golden set. A stage 01 test guarantees the precondition: every anchor lies whole inside at least one chunk, so recall can reach 1.0.

Anchors have a cost, and the taxonomy below names it. A chunk can answer the question in other words without containing the anchor, and the metric counts it as a miss. Keep anchors specific and check misses by reading them.

### Reading the numbers by kind

The hashing pipeline with lexical reranking and MMR, pinned in the stage 05 tests: recall@10 0.729, MRR 0.536, nDCG@10 0.583 overall. By kind: lexical recall 1.000 and MRR 0.854, factual 0.938 and 0.656, conceptual 0.250 and 0.098. The overall average hides the split: the pipeline is near-perfect on two kinds and nearly blind on the third. With bge-small and a cross-encoder (stage 08), conceptual recall rises to 0.438 and overall recall@10 to 0.781.

Two diagnostics sit next to the headline. Recall of the fused pool at 50 (0.792 for hashing, 0.875 for bge-small) is the ceiling any reranker can reach; it separates "the first stage never found it" from "the reranker did not promote it". And stage 05 pins numbers within 0.02, with floors below them, so a change that breaks retrieval fails a test rather than a demo. The recall floor itself is a lesson: the course's original target was 0.80, the pool ceiling was 0.792, so the floor became the measured value rounded down, 0.70.

### The failure taxonomy

Stage 07 is the [M2 error-analysis](../../m2/01-error-analysis-first/) method applied to retrieval. For every golden query whose relevant chunk is outside the top 10, you look at the query, the anchor's chunk, the top 10, and the chunk's rank in the vector list, the full-text list, the fused pool and the reranked pool, and assign one failure kind:

- `vocabulary-gap`: the query and the passage share no words; neither list reaches the chunk.
- `chunk-boundary`: the cut separated the anchor from the words or heading that would have matched.
- `ranking`: the chunk is in the fused pool but fusion ranks it low.
- `reranker-demotion`: fusion had it in the top 10 and the reranker pushed it out.
- `anchor-ambiguity`: another chunk in the top 10 answers the question, without the anchor.

Each row also names a fix from a fixed list: `hybrid-weights`, `smaller-chunks`, `contextual-chunk-headers`, `query-rewrite`, `better-embedder`. The reference pipeline has 13 misses, all conceptual but one. Stage 07 asks you to classify them; the distribution you find decides the fix: if most misses are vocabulary gaps, no reranker over the same pool can fix them, and a better embedder, query rewriting or contextual chunk text (Anthropic's contextual embeddings cut top-20 failures by 35%) might.

## Common pitfalls

- **nDCG with the ideal over k.** Silently deflates every query with fewer relevant items than k. One relevant chunk at rank 1 must score 1.0.
- **Only an overall average.** The course's 0.729 is 1.000, 0.938 and 0.250 by kind. Always split by query type.
- **A golden set written from the retriever's output.** Questions phrased after seeing what the system returns measure its vocabulary, not the users'. Write conceptual queries that do not reuse the passage's words.
- **Judging relevance with an unvalidated model.** A judge needs its own agreement check against human labels, as M2 covers; deterministic anchors avoid the problem for retrieval.
- **Tuning on the whole golden set.** Every threshold fitted to the 48 queries is optimistic on new ones. Keep part of the set aside, or add queries from real misses as they appear.

## What interviewers ask

**How do you evaluate a RAG system?**
Separately for retrieval and generation, retrieval first. Build a golden set of queries with known relevant passages from the corpus, measure recall@k, MRR and nDCG@k at the k you send to the model, split by query type, and only then judge answers with a validated judge. A wrong answer with the passage absent from the top k is a retrieval bug.

**Define nDCG and say what the ideal is.**
DCG sums gain / log2(rank + 1) over the top k; nDCG divides it by the DCG of the best possible ranking for that query. With binary gains the ideal puts all relevant items first, so it has min(k, relevant) terms. Using k terms makes a perfect single-answer result score 0.22 at k = 10 instead of 1.0.

**How do you get relevance labels without labelling every chunk?**
Tie each query to a verbatim anchor phrase in the source and call a chunk relevant when it contains the anchor. That is deterministic, cheap and survives re-chunking; the cost is that a chunk answering in other words counts as a miss, which error analysis has to catch.

**Your recall@10 is 0.75. What do you do next?**
Check the pool's recall at 50 to see whether the first stage or the reranker loses the chunk, split by query kind, then read every miss and classify it. If most misses are vocabulary gaps on conceptual queries, the next step is a better embedder or query rewriting, not reranker tuning.

## Sources

- [AI Evals: Everything You Need to Know](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, 2026-09-18, question "How should I approach evaluating my RAG system?", checked 2026-10-17
- Kalervo Järvelin, Jaana Kekäläinen, [Cumulated gain-based evaluation of IR techniques](https://doi.org/10.1145/582415.582418), ACM Transactions on Information Systems 20(4), 2002, pages 422 to 446, DOI 10.1145/582415.582418, checked 2026-10-17
- [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval), Anthropic, 2024-09-19, the failure-rate results, checked 2026-10-17
- Course code (repository files, not web sources): stages 01, 05 and 07 in `course/m4-retrieval-lab/README.md` and their tests, the corpus README `fixtures/corpus/README.md`, the live record `course/m4-retrieval-lab/fixtures/live_local_models_run.json`, the lesson helpers in `course/m4-retrieval-lab/lesson_support/src/retrieval_lab_lessons/`
