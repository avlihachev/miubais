---
title: When not to build RAG
description: Three ways to get knowledge into an agent's context (put the whole corpus in the prompt with caching, let the agent search with tools, or build an index), how to choose between them by corpus size, change rate and query shape, what the "Is RAG dead?" argument actually targets, and why the course indexes a corpus that would fit in the prompt.
module: m4
order: 1
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
  - url: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
    title: Effective context engineering for AI agents
    published: 2025-09-29
    checked: 2026-10-17
  - url: https://hamel.dev/blog/posts/evals-faq/
    title: "AI Evals: Everything You Need to Know"
    published: 2026-09-18
    checked: 2026-10-17
---

**Prerequisites:** [M0 lesson 03](../../m0/03-prompt-caching/), which covers how a cached prefix is priced and when it is reused.

## Why this matters for the factory

A factory agent needs knowledge its weights do not have: your runbooks, your architecture decisions, last quarter's incident reports, the code it is about to change. Since 2023 the default answer has been a pipeline: cut the documents into chunks, embed them, keep the top few by cosine similarity, paste them into the prompt. Retrieval is not the problem; the problem is building that pipeline before asking whether it is needed, and never measuring it.

There are three ways to get knowledge into the context, and an index is only one of them. You can put the whole corpus in the prompt and let prompt caching pay for the repetition. You can give the agent tools and let it look things up as it works. Or you can build an index ahead of time and retrieve from it. Each has a cost, a latency and a failure mode, and the right choice changes with the size of the corpus, how often it changes and what the questions look like.

This module treats retrieval as a component: something with an interface, tests and metrics, that you add when the numbers say so. This lesson is about the decision. Lessons 02 to 06 build the component and measure it.

## Core idea

Three regimes, decided mostly by size and change rate.

**The corpus fits.** Anthropic's contextual retrieval post opens with the simplest option: "If your knowledge base is smaller than 200,000 tokens (about 500 pages of material)", you can include the whole knowledge base in the prompt, and prompt caching makes that "significantly faster and more cost-effective". Nothing is retrieved, so nothing is missed. The model sees every document every time.

**The corpus is navigable and changes all the time.** A code repository is the standard example. Files change with every commit, names are precise, and the agent already has tools that can find them. Anthropic's context engineering post describes agents built "just in time" that "maintain lightweight identifiers (file paths, stored queries, web links, etc.)" and load the data with tools when they need it. For code, Claude Code uses glob and grep, "effectively bypassing the issues of stale indexing and complex syntax trees". The price is time: "runtime exploration is slower than retrieving pre-computed data."

**The corpus is large, stable enough, and asked in natural language.** Tens of thousands of documents, many questions per version of the corpus, users who ask "how do we rotate the signing key" rather than naming a file. Here an index earns its keep: the work of reading the corpus is done once at indexing time, and each question pays only for a search and a few chunks. The same post says the mixed approach, some context up front and the rest retrieved, "might be better suited for contexts with less dynamic content, such as legal or finance work."

The regimes overlap. Claude Code itself is a hybrid: "CLAUDE.md files are naively dropped into context up front, while primitives like glob and grep" let it find the rest. A support assistant may put the product's top twenty articles in a cached prefix and retrieve from the long tail.

## Mechanics

### Measure the corpus before you design anything

The first number is the size of what you want the model to know. The sample counts the course's own fixture corpus: the 29 Markdown documents and 3 stories that the exercise indexes.

Sample: `site/samples/m4/01-1.py`.

```python
from retrieval_lab_lessons import corpus_size

size = corpus_size("fixtures/corpus")
print(f"{size['documents']} documents, {size['chars']:,} characters, {size['words']:,} words")
print(f"largest document: {size['largest']:,} characters")
print(f"estimate at 4 characters per token: {size['tokens_estimate']:,} tokens")
print("under 200,000 tokens:", size["tokens_estimate"] < 200_000)
```

Output, run on 2026-10-23:

```
32 documents, 501,311 characters, 76,477 words
largest document: 31,497 characters
estimate at 4 characters per token: 125,327 tokens
under 200,000 tokens: True
```

Four characters per token is a rule of thumb for English prose, not a count: code and tables tokenise differently, so count with the model's tokenizer before you commit. The whole corpus the exercise indexes would fit under Anthropic's 200,000-token line, and for a real assistant over these 32 documents, a cached prompt would be the first design to try.

The exercise indexes it anyway, on purpose. A small corpus is where you can read every failure: 48 golden queries, 653 chunks, and a test suite that tells you which query missed and why. What you learn there transfers to the corpus that does not fit. In a design review, "this would fit in context; we are indexing it to learn the pipeline" is a fine sentence, while "we need RAG" for a 125,000-token corpus is not.

### What each option costs

**Long context.** Every question pays for the whole corpus as input tokens. Caching changes the price of the repeated prefix, not its existence: the contextual retrieval post cites prompt caching "reducing latency by > 2x and costs by up to 90%". The cache has a lifetime, so a corpus asked about rarely pays full price more often; [M0 lesson 03](../../m0/03-prompt-caching/) has the arithmetic. The failure mode is attention, not recall: the relevant paragraph is in the context, among 500 pages of others.

**Agentic search.** No index to build or keep fresh, and the agent can follow a lead: grep for a symbol, open the file, grep for its caller. Each step is a model turn and a tool call, so latency and cost grow with the number of steps, and the agent can give up early or search for the wrong word. This works best when the corpus has precise names (paths, symbols, error codes) and the agent knows what to look for.

**An index.** You pay at write time: chunking, embedding every chunk, storing vectors and a full-text index, and re-indexing what changes. A question then costs one embedding call, two searches and a reranker pass, typically far below a model turn. The failure mode is the one this module spends five lessons on: the chunk that holds the answer is not in the top k, and the model either answers from the wrong chunks or refuses.

### When an index earns its keep

Build one when most of these hold:

- The corpus is well over what you can afford to send per question, even cached, or it does not fit at all.
- Many questions are asked per version of the corpus, so the indexing cost is spread thin.
- Questions are phrased by people in their own words, not as identifiers an agent could grep for.
- The latency budget rules out several tool-calling turns per question.
- You can write down what "found the right passage" means and measure it, which is what lesson 05's golden set does.

Skip it, or postpone it, when the corpus fits, when it changes faster than you can re-index, or when the users are agents working on code that they can search directly.

### The "Is RAG dead?" argument

A recurring argument declares retrieval obsolete because context windows grew or because coding agents stopped using vector databases. Hamel Husain and Shreya Shankar's evals FAQ answers this directly: the viral argument targets "naive vector database retrieval for autonomous coding agents, not RAG as a whole." Coding assistants such as Claude Code still retrieve, "they just employ agentic search instead of relying solely on vector databases."

Retrieval is a step in which you select what goes into the context. Vector search is one way to do it, full-text search another, a grep loop a third, and "send everything" is the degenerate case where selection is skipped. The design question is which selection mechanism fits this corpus and how you know it works.

### What the rest of the module builds

The exercise builds the third regime as a component over Postgres: a Markdown-aware chunker, a hashing embedder that needs no model, a pgvector table with a generated full-text column, vector and full-text search fused by reciprocal rank, a reranker and MMR, metrics on a golden set, and an answer prompt that cites its sources and refuses when nothing supports it. Two live stages swap in local models (a 384-dimension embedder and a cross-encoder) and ask Claude for cited answers. Lesson 06 returns to agentic retrieval and where it sits next to an index.

## Common pitfalls

- **Indexing a corpus that fits.** A 300-page handbook behind a vector store loses answers the model would have read in a cached prompt. Measure the corpus first.
- **Vector search for identifiers.** Embeddings find content about error codes in general and can miss the exact code; the contextual retrieval post uses "TS-999" as its example. Lesson 03 adds full text.
- **No retrieval metrics.** Prompt tuning cannot help when the answer chunk was never in the top 10. The FAQ's advice is to "debug retrieval first using IR metrics, then tackle generation quality".
- **A stale index nobody owns.** An index is a cache of the corpus. Without a re-indexing job and a freshness check, it answers from last quarter's runbook.
- **Treating agentic search as free.** It saves the index and spends turns. Count tool calls and latency per question before you replace an index with it.

## What interviewers ask

**When would you not build a retrieval pipeline?**
When the corpus fits in the context and caching makes repeated questions affordable; Anthropic's threshold is a knowledge base smaller than 200,000 tokens. Also when the corpus changes faster than an index can follow and the users are agents that can search it with tools, as Claude Code does with glob and grep. I would measure the corpus in tokens before designing anything.

**Is RAG dead now that context windows are large?**
No. What the argument targets is naive vector retrieval for coding agents, and those agents still retrieve with agentic search. Selection is always there; the choice is the mechanism: full context, tool-driven search, an index, or a mix such as a cached prefix plus retrieval for the long tail.

**What does agentic search cost compared to an index?**
No indexing and no staleness, but each lookup is a model turn plus a tool call, so latency and cost grow with the number of steps, and Anthropic says that runtime exploration is slower than retrieving pre-computed data. An index moves the work to write time and makes each question cheap, at the price of keeping it fresh and measuring recall.

**Your corpus is 140,000 tokens. Design the assistant.**
Start with the corpus in a cached prompt and measure answer quality and cost per question. Build an index only if cost or latency per question is too high, the corpus is about to grow past the window, or many users ask in natural language at volume. If I index, I build a golden set first so the retrieval step has its own recall number.

## Sources

- [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval), Anthropic, 2024-09-19, sections A note on simply using a longer prompt and the BM25 example, checked 2026-10-17
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), Anthropic Engineering, 2025-09-29, section Context retrieval and agentic search, checked 2026-10-17
- [AI Evals: Everything You Need to Know](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, 2026-09-18, questions "Is RAG dead?" and "How should I approach evaluating my RAG system?", checked 2026-10-17
- Course code (repository files, not web sources): the corpus in `fixtures/corpus/` and its `README.md`, `course/m4-retrieval-lab/README.md`, the lesson helpers in `course/m4-retrieval-lab/lesson_support/src/retrieval_lab_lessons/`
