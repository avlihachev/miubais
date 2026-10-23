---
title: M4 Retrieval as a component
freshness: skip
---

Retrieval built and measured as a component rather than a feature: when not to build it at all, chunking along a document's structure, hybrid search in Postgres fused by reciprocal rank, reranking and MMR over a candidate pool, recall, MRR and nDCG on a golden set with deterministic relevance, and answers that cite their sources or refuse.

## Lessons

- [01 When not to build RAG](./01-when-not-to-rag/)
- [02 Chunking and embeddings](./02-chunking-and-embeddings/)
- [03 Hybrid search](./03-hybrid-search/)
- [04 Reranking and MMR](./04-reranking-and-mmr/)
- [05 Retrieval metrics and golden sets](./05-retrieval-metrics-and-golden-sets/)
- [06 Citations, faithfulness and agentic retrieval](./06-citations-faithfulness-and-agentic-retrieval/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M4 retrieval lab](/exercises/m4-retrieval-lab/): build `retrieval_lab`, a hybrid retrieval pipeline over Postgres with pgvector, on a 32-document corpus with a 48-query golden set, with tests and hints.

1. `01-chunker`: load the corpus and chunk Markdown by headings and paragraphs, never splitting a code fence.
2. `02-embed-and-store`: a deterministic hashing embedder and a pgvector table with a generated full-text column (needs Docker).
3. `03-hybrid-retrieval`: vector and full-text search that never raise on user input, fused with reciprocal rank fusion (needs Docker).
4. `04-reranker`: a BM25 reranker over the fused candidates and MMR against near-duplicates (needs Docker).
5. `05-metrics`: recall, precision, MRR and nDCG on the golden set, with the reference numbers pinned (needs Docker).
6. `06-answer-assembly`: a numbered, cited answer prompt, a refusal below the support floor, and a faithfulness check (needs Docker).
7. `07-retrieval-error-analysis`: classify every golden query the pipeline misses and name a fix for each (judgment stage; needs Docker).
8. `08-live-local-models`: run the pipeline with a local embedding model and a cross-encoder (needs Docker and the local models, 66.5 MB and 91 MB, about 160 MB).
9. `09-live-answer`: ask Claude for cited answers to three golden queries (needs Docker and a Claude login).
