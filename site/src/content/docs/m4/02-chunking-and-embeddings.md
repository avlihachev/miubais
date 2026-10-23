---
title: Chunking and embeddings
description: How the exercise cuts Markdown into chunks along headings and paragraphs without breaking code fences, what overlap and heading paths buy, a deterministic hashing embedder as a baseline and why it works at all, local embeddings with fastembed, and Voyage as the hosted option Anthropic points to.
module: m4
order: 2
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
  - url: https://platform.claude.com/docs/en/build-with-claude/embeddings
    title: Embeddings
    checked: 2026-10-17
  - url: https://github.com/qdrant/fastembed
    title: FastEmbed README
    checked: 2026-10-17
  - url: https://github.com/pgvector/pgvector
    title: pgvector README
    checked: 2026-10-17
  - url: https://hamel.dev/blog/posts/evals-faq/
    title: "AI Evals: Everything You Need to Know"
    published: 2026-09-18
    checked: 2026-10-17
---

**Prerequisites:** [lesson 01](../01-when-not-to-rag/), which decides when an index is worth building at all.

## Why this matters for the factory

The chunk is what the search returns, what the reranker scores, what the model reads and cites, and what the metrics count as relevant or not. A chunk that cuts a code block in half gives the model a command without its flags. A chunk that separates a paragraph from the heading that names its subject cannot be found by a query that uses the heading's words. Stage 07's error analysis has a name for this, chunk-boundary: the cut separated the answer from the words that would have matched.

The embedder decides what "similar" means. A model that maps "cache hits" and "reading from the prompt cache" close together finds paraphrases; a model that only counts shared character patterns does not. Before choosing a hosted model, measure what a baseline with no model at all gets you: that is the number every model has to beat.

## Core idea

Cut along the structure the author already gave the document, and keep a record of where each piece came from.

- **Boundaries.** Headings start sections; blank lines separate blocks; a fenced code block is one block, whatever it contains. A chunk never spans two sections.
- **Size.** Pack blocks greedily up to a character budget (1,200 in the exercise). A block larger than the budget becomes one oversized chunk rather than being split.
- **Overlap.** Start the next chunk one block before the previous one ended, so an answer that straddles two paragraphs appears whole in at least one chunk.
- **Provenance.** Every chunk records `doc_id`, `chunk_id`, `start_char`, `end_char`, `heading_path` and its text, and `doc.text[start_char:end_char] == text`. Citations, deduplication and re-indexing all depend on this.

Then map each chunk to a vector, so that "close in meaning" becomes "close in angle", and store the vectors next to the text.

## Mechanics

### The chunker on an invented runbook

The sample uses the lesson helpers, small re-implementations written for the page, not the exercise's reference. It chunks an invented runbook with a 60-character budget so that every rule shows up in a few lines: a heading path, a fence longer than the budget with a `#` line inside it, and overlap.

Sample: `site/samples/m4/02-1.py`.

```python
from retrieval_lab_lessons import toy_chunk

doc = """# Runbook

Restart the worker when the queue backs up.

## Deploy

Tag the release first.

~~~bash
./deploy.sh --env prod

# rollback if the error rate rises
./deploy.sh --rollback
~~~

Watch the error rate.

Page the on-call engineer.

Write the incident note.
"""
for c in toy_chunk("runbook", doc, max_chars=60, overlap=1):
    body = c.text.replace("\n", "\\n")
    print(f"{c.chunk_id} [{c.start_char}:{c.end_char}] {c.heading_path!r}")
    print(f"  {len(c.text):>3} chars  {body[:58]}")
```

Output, run on 2026-10-17:

```
runbook#000 [0:54] 'Runbook'
   54 chars  # Runbook\n\nRestart the worker when the queue backs up.
runbook#001 [56:89] 'Runbook > Deploy'
   33 chars  ## Deploy\n\nTag the release first.
runbook#002 [91:184] 'Runbook > Deploy'
   93 chars  ~~~bash\n./deploy.sh --env prod\n\n# rollback if the error
runbook#003 [186:235] 'Runbook > Deploy'
   49 chars  Watch the error rate.\n\nPage the on-call engineer.
runbook#004 [209:261] 'Runbook > Deploy'
   52 chars  Page the on-call engineer.\n\nWrite the incident note.
```

The H1 and its paragraph form the first section, so chunk 000 cannot absorb the `## Deploy` heading. The fence (here with tildes; backticks work the same way) is 93 characters against a budget of 60, and it stays one chunk: the blank line inside it does not end a block and `# rollback ...` is not a heading, because inside a fence nothing is Markdown. A naive splitter on blank lines would have produced a chunk that starts with `# rollback` and a heading path that never existed. Chunks 003 and 004 share "Page the on-call engineer.": that is the overlap of one block, and the offsets show it (209 is before 235). The exercise's chunker follows the same rules, with one more detail: the carried block is dropped when keeping it would leave no room for a new block, so overlap can never stall the packer.

### What the heading path is for

`heading_path` (`Runbook > Deploy`) is the cheapest form of context a chunk can carry. A paragraph that says "run it again with `--rollback`" means nothing on its own; under `Runbook > Deploy` it is findable. Anthropic's contextual retrieval goes further and has a model write chunk-specific context: their example turns "The company's revenue grew by 3% over the previous quarter." into a chunk prefixed with "This chunk is from an SEC filing on ACME corp's performance in Q2 2023; the previous quarter's revenue was $314 million." They report a one-time cost of "$1.02 per million document tokens" with prompt caching, and that contextual embeddings alone cut the top-20 retrieval failure rate by 35%. A heading path is the deterministic version with no model call; `contextual-chunk-headers` is one of the fixes stage 07 lets you propose.

### Chunk size

The evals FAQ: "I treat chunk size as a hyperparameter to tune." Small chunks make each hit precise but scatter an answer across pieces and lose the surrounding words that would have matched; large chunks keep context but dilute the embedding and cost more tokens per hit. The exercise's default, 1,200 characters with one block of overlap, turns the 32-document corpus into 685 chunks. Change it, and the golden set from lesson 05 tells you whether recall moved. Because relevance is defined by an anchor phrase rather than a chunk id, the golden set survives re-chunking.

### A hashing embedder, and why it works at all

Stage 02 pins an embedder that needs no model: tokens are the lowercase words, the word bigrams, and every three-character slice of every word; each token is hashed with `blake2b` into one of 256 positions with a sign taken from the hash's top bit, the counts are summed, and the vector is L2-normalised. It is deterministic across machines and processes, so test numbers can be pinned.

Sample: `site/samples/m4/02-2.py`.

```python
from retrieval_lab_lessons import cosine, hash_embed, hash_tokens

print(hash_tokens("Cache hits")[:6])
vec = hash_embed("Cache hits")
print(
    f"dims {vec.shape[0]}, nonzero {int((vec != 0).sum())}, norm {float((vec**2).sum()) ** 0.5:.3f}"
)

query = "how do cache hits lower the bill"
for text in (
    "Cache hits are billed at a tenth of the input price.",
    "Cached prefixes make repeated requests cheaper.",
    "Reading from the prompt cache costs less than fresh input.",
    "The tell-tale heart beat louder under the floor.",
):
    print(f"{cosine(hash_embed(query), hash_embed(text)):+.3f}  {text}")
```

Output, run on 2026-10-17:

```
['cache', 'hits', 'cache hits', 'cac', 'ach', 'che']
dims 256, nonzero 8, norm 1.000
+0.373  Cache hits are billed at a tenth of the input price.
+0.099  Cached prefixes make repeated requests cheaper.
+0.153  Reading from the prompt cache costs less than fresh input.
+0.309  The tell-tale heart beat louder under the floor.
```

Why it works: two texts that share words, word pairs or character trigrams add to the same positions, so their dot product grows with the overlap; a random signed projection like this roughly preserves that overlap. Trigrams give partial credit across inflections: "cache" and "Cached" share `cac`, `ach` and `che`. The first sentence shares the bigram "cache hits" and scores highest.

Why it fails: it has no idea what anything means. The off-topic sentence from Poe scores 0.309, above both paraphrases, because the only token it shares with the query is "the", counted twice (as a word and as its own trigram), and other tokens land on the same few of 256 positions with the same sign. On the golden set this is the conceptual column: with the full hashing pipeline (full text, reranker and MMR included) conceptual recall@10 is 0.250, while lexical and factual queries reach 1.000. As a baseline it is good enough to build and test the whole pipeline, and useless for paraphrase.

### Local embeddings with fastembed

Stage 08 swaps in a real model through fastembed, which runs ONNX models on the CPU: "We don't require a GPU and don't download GBs of PyTorch dependencies, and instead use the ONNX Runtime." The README's example is the model the exercise uses, `TextEmbedding(model_name="BAAI/bge-small-en-v1.5")`, a "Vector of 384 dimensions". The exercise's `FastEmbedder` imports fastembed only on its first non-empty call and keeps the model under `~/.cache/fastembed` (or `$FASTEMBED_CACHE_PATH`), because fastembed's own default is a temporary directory.

The live record has the timing: embedding the 653 chunks took 50 seconds on a shared CPU; the quantised bge-small download was 66.5 MB. Conceptual recall@10 with the full pipeline rose from 0.250 (hashing) to 0.438 (bge-small plus a cross-encoder, lesson 04). Conceptual queries remain the weakest kind.

### Hosted embeddings: Voyage

Anthropic's embeddings page starts with: "Anthropic does not offer its own embedding model." It points to Voyage AI and lists `voyage-4-large`, `voyage-4` and `voyage-4-lite` (1024 dimensions by default, with 256, 512 and 2048 available), `voyage-code-4` for code retrieval, the open-weight `voyage-4-nano`, and `voyage-context-4`, which embeds chunks with their document's context (up to 120,000 tokens with automatic chunking). Two details matter for design. Queries and documents are embedded differently: `input_type="query"` prepends "Represent the query for retrieving supporting documents: " and `input_type="document"` prepends "Represent the document for retrieval: ". And "Voyage AI embeddings are normalized to length 1", so dot product and cosine give the same ranking.

### Storing vectors

The exercise stores each chunk with `embedding vector(<dims>)` in a pgvector column and refuses to mix dimensions: `Schema.create` and `upsert` raise `ValueError` when the embedder's `dims` differ from the table's. pgvector indexes `vector` columns up to 2,000 dimensions with HNSW. An index is tied to one embedding model: changing the model means re-embedding every chunk, which is why stage 08 builds a fresh 384-dimension table rather than reusing the 256-dimension one.

## Common pitfalls

- **Fixed-size windows.** Cutting every 1,000 characters splits sentences, tables and code fences. Cut along the document's own structure first.
- **No offsets.** Without `start_char` and `end_char` you cannot show the cited passage, deduplicate overlapping hits or re-index one changed section.
- **Mixing embedders in one index.** Vectors from two models, or two dimension settings of one model, are not comparable. Pin the model per table and fail loudly on mismatch.
- **Ignoring query and document asymmetry.** Hosted models that take an `input_type` expect you to use it; the Voyage FAQ says not to omit it for retrieval, because marking text as a query or a document "can lead to better retrieval quality."
- **Choosing a model before having a baseline.** Without the hashing numbers you cannot say what the 66.5 MB model bought you.

## What interviewers ask

**How do you chunk technical documentation?**
Along its structure: headings start sections, blank lines separate blocks, a code fence is one block however long, and a chunk never crosses a section. Pack blocks up to a budget with one block of overlap, keep the heading path as metadata, and record offsets so every chunk maps back to the source. Then tune the size against a golden set.

**What is overlap for, and what does it cost?**
It keeps an answer that straddles a boundary whole in at least one chunk. The cost is duplicated text in the index and near-duplicate hits in the top k, which is one reason to run MMR after reranking.

**Why would you ever use a hashing embedder?**
As a deterministic baseline and for tests: no model, no download, the same vector on every machine. It captures shared words and character patterns, so it handles exact and near-exact matches, and it fails on paraphrase. In the course it gives conceptual recall@10 of 0.250, which is the number a real model has to beat.

**Which embedding model would you use with Claude?**
Anthropic has no embedding model of its own; its docs point to Voyage, with `voyage-4` as the balanced default, `voyage-code-4` for code and `voyage-context-4` for chunks that need document context, used with `input_type` for queries and documents. For a local or offline setup, a small open model such as bge-small through fastembed. Either way I would compare it against a baseline on my own golden set.

## Sources

- [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval), Anthropic, 2024-09-19, the contextualized chunk example, its cost and the failure-rate results, checked 2026-10-17
- [Embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings), Claude docs, sections Available models and FAQ, checked 2026-10-17
- [FastEmbed README](https://github.com/qdrant/fastembed), version 0.9.0, sections on text embeddings and rerankers, checked 2026-10-17
- [pgvector README](https://github.com/pgvector/pgvector), version 0.8.7, the vector type, HNSW indexing and dimension limits, checked 2026-10-17
- [AI Evals: Everything You Need to Know](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, 2026-09-18, question on choosing chunk size, checked 2026-10-17
- Course code (repository files, not web sources): stages 01, 02 and 08 in `course/m4-retrieval-lab/README.md` and their tests, the live record `course/m4-retrieval-lab/fixtures/live_local_models_run.json`, the lesson helpers in `course/m4-retrieval-lab/lesson_support/src/retrieval_lab_lessons/`
