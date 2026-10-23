---
title: "Interview angle: retrieval as a component"
description: The questions an interviewer asks about when to build retrieval, chunking, embeddings, hybrid search, rank fusion, reranking, retrieval metrics and cited answers, a system-design prompt for a support assistant over 40,000 internal documents with daily updates, and what a short take-home on this topic looks like.
module: m4
order: 7
freshness: skip
---

**Prerequisites:** lessons 01 to 06 of [M4](../), which this page assumes you have read.

This page collects what lessons 01 to 06 prepare you to answer out loud. Each answer points back to the lesson that covers it in depth.

## What they ask

**1. When would you not build a retrieval pipeline?**
When the corpus fits in context and caching makes repeated questions affordable: Anthropic's contextual retrieval post sets the line at a knowledge base smaller than 200,000 tokens. Also when the corpus is code that changes with every commit and the users are agents that can search it with glob and grep, which avoids stale indexes at the cost of slower runtime exploration. The course's own 32-document corpus is about 138,000 tokens by a four-characters-per-token estimate, so it would fit; the exercise indexes it to learn the pipeline. "Is RAG dead?" targets naive vector retrieval for coding agents, not retrieval as such ([lesson 01](../01-when-not-to-rag/)).

**2. How do you chunk technical documents?**
Along their structure: headings start sections, blank lines separate blocks, a code fence is one block however long, and a chunk never spans two sections. Pack blocks up to a budget (1,200 characters in the course) with one block of overlap, keep the heading path, and record offsets so each chunk maps back to its source. Chunk size is a hyperparameter tuned on a golden set ([lesson 02](../02-chunking-and-embeddings/)).

**3. Which embeddings, and how do you know they are good enough?**
Anthropic has no embedding model; its docs point to Voyage (`voyage-4`, `voyage-code-4`, `voyage-context-4`, 1024 dimensions by default) with separate query and document input types. Locally, a small model such as bge-small (384 dimensions) through fastembed. Measure against a baseline: the course's hashing embedder reaches conceptual recall@10 of 0.250 with the full pipeline, bge-small with a cross-encoder 0.438 ([lesson 02](../02-chunking-and-embeddings/)).

**4. Why hybrid search, and how do you combine the two lists?**
Embeddings miss exact identifiers and full text misses paraphrase. Run Postgres full text (`websearch_to_tsquery`, which never raises on user input, ranked by `ts_rank_cd`) and pgvector cosine search, then fuse with reciprocal rank fusion: `score(d) = Σ 1 / (60 + rank_r(d))`. Ranks, not scores, because cosine and cover density are on different scales; a chunk 30th in both lists (2/90) correctly beats one first in a single list (1/61). Watch pgvector's `hnsw.ef_search`, 40 by default, which caps an HNSW `LIMIT` ([lesson 03](../03-hybrid-search/)).

**5. What does a reranker buy, and how big should the candidate pool be?**
A cross-encoder reads query and chunk together and ranks better than the first stage, but cannot be precomputed, so it runs on a pool. Anthropic retrieved 150 and kept 20; the course keeps 10 of 50. In the course, reranking took recall@10 from 0.656 to 0.750 and MRR from 0.406 to 0.545 (BM25 reranker), and MRR from 0.552 to 0.648 with real models. The pool's recall is the ceiling: 0.792 at 50 for hashing, 0.875 for bge-small. MMR at λ 0.7 then removes near-duplicates for a 0.009 MRR cost ([lesson 04](../04-reranking-and-mmr/)).

**6. How do you evaluate retrieval?**
Separately from generation and first. A golden set of queries with known passages, recall@k, MRR and nDCG@k at the k you send, split by query kind. nDCG's ideal runs over min(k, relevant), so one relevant chunk at rank 1 scores 1.0. The course ties each query to a verbatim anchor phrase, making relevance deterministic and robust to re-chunking; its 0.729 overall recall is 1.000, 0.938 and 0.250 by kind ([lesson 05](../05-retrieval-metrics-and-golden-sets/)).

**7. Recall is stuck. What next?**
Check pool recall to see whether the first stage or the reranker loses the chunk, then read every miss and classify it: vocabulary gap, chunk boundary, ranking, reranker demotion, anchor ambiguity. If most misses are vocabulary gaps on conceptual queries, the next step is a better embedder, query rewriting or contextual chunk text, not tuning fusion. The live 0.781 missed the course's original target of 0.85 because conceptual queries paraphrase without the document's words, and the floor was set from the measurement ([lesson 05](../05-retrieval-metrics-and-golden-sets/)).

**8. How do you keep answers grounded, and when does the system refuse?**
Number the sources, require a citation per sentence and an exact refusal sentence, and check mechanically for uncited sentences and invented source numbers. Refuse before calling the model when too few chunks clear a support floor measured for that reranker (a BM25 4.0 in the course, refusing six off-corpus questions and passing 47 of 48 golden ones). A citation is not proof of support; that needs a validated judge. The course's live run: three of three answers cited a relevant chunk, $0.099 ([lesson 06](../06-citations-faithfulness-and-agentic-retrieval/)).

## System design prompt

"Design retrieval for a support assistant over 40,000 internal documents with daily updates; say what you measure."

A short model outline:

- **Size it first.** 40,000 documents at a few thousand tokens each is tens of millions of tokens, far past the 200,000-token line, so an index is justified. Ask how many questions a day and what latency: that sets the reranker budget. Put a small cached prefix of the most-used articles in front if a handful answer most questions.
- **Ingestion.** A job per source system (wiki, tickets, runbooks) that emits documents with stable ids, `updated_at`, owner and access labels. Chunk by structure with heading paths and offsets. Embed with a hosted model (Voyage with `input_type`) or a local one if data must stay in-house. Store in Postgres: text, generated `tsvector` with GIN, `vector` with HNSW, metadata columns, one table per embedding model.
- **Daily updates.** Re-chunk only changed documents by content hash; upsert by chunk id and delete chunks of removed sections; record the index's high-water mark and alert when it lags the sources by more than a day. A model change means a new table built alongside and switched when its golden numbers are at least as good.
- **Query path.** Access filter first (only chunks the asker may read), then vector top 50 and full-text top 50, RRF with k = 60, a cross-encoder over the fused pool, MMR at about 0.7, top 5 to 10 into a numbered, cited prompt. Raise `hnsw.ef_search` to the pool size, and size the pool by measured pool recall.
- **Answer contract.** Citation per sentence, an exact refusal sentence, a support floor on reranker scores measured on off-corpus and golden queries, a mechanical check on every answer, and a fallback to a capped agent loop that rephrases when the pipeline refuses.
- **What to measure.** Offline: recall@k, MRR and nDCG@k on a golden set built from the corpus (facts extracted, questions written, conceptual ones without the document's words), split by query type and source; pool recall@50; per-kind numbers pinned in CI so a regression fails a build. Online: refusal rate, uncited and invalid citation counts, thumbs-down tied to the retrieved chunk ids, latency per stage, cost per answer, index lag. Weekly: read the misses and classify them, and add real failed questions to the golden set.

Close with the trades: a bigger pool raises the ceiling and every query's latency; a stricter floor refuses more answerable questions; contextual chunk text helps vocabulary gaps and costs a model call per chunk at indexing time; and every number on the golden set is optimistic until it includes questions real users asked.

## Take-home shape

A good 2 to 4 hour take-home on this topic hands the candidate a small Markdown corpus (20 to 40 documents with headings and code blocks), a golden set of 30 to 50 queries with anchor phrases and kinds, a Postgres container with pgvector, and a stubbed model call, and asks for three things:

1. **A chunker and hybrid search with tests.** Structure-aware chunks with offsets and heading paths, a test that a long fence stays whole, full-text search that does not raise on quotes and operators, and RRF by rank with the k = 60 arithmetic tested (2/90 against 1/61).
2. **Metrics and a short report.** Recall@k, MRR and nDCG@k with a hand-computed test (including one relevant item at rank 1 scoring 1.0), numbers before and after a reranker, split by query kind, and a paragraph on the misses classified by cause.
3. **A cited answer path.** A numbered prompt, a refusal below a measured floor with no model call, and a check that flags uncited sentences and source numbers outside the given range.

Grade on the edges (a fence with blank lines and `#` inside, a query with a stray quote, a single-answer query in nDCG, a citation of a source that was not given), on whether fusion uses ranks, and on honesty about the numbers: a submission that reports one overall recall without the per-kind split, or tunes on the whole golden set and calls it a result, fails that criterion.
