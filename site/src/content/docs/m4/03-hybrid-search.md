---
title: Hybrid search
description: Postgres full-text search from tsvector to websearch_to_tsquery and ts_rank_cd, pgvector's cosine operator and HNSW index with its ef_search cap, reciprocal rank fusion with k = 60 and why it fuses ranks rather than scores, and where each side wins on the course's lexical and conceptual queries.
module: m4
order: 3
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:fastembed": "0.9.0"
  "pypi:pgvector": "0.5.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://www.postgresql.org/docs/17/textsearch-controls.html
    title: "PostgreSQL 17: 12.3. Controlling Text Search"
    checked: 2026-10-17
  - url: https://github.com/pgvector/pgvector
    title: pgvector README
    checked: 2026-10-17
  - url: https://github.com/pgvector/pgvector-python
    title: pgvector-python README
    checked: 2026-10-17
  - url: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf
    title: Reciprocal rank fusion outperforms Condorcet and individual rank learning methods
    published: 2009-07-19
    checked: 2026-10-17
  - url: https://www.anthropic.com/engineering/contextual-retrieval
    title: Introducing Contextual Retrieval
    published: 2024-09-19
    checked: 2026-10-17
---

**Prerequisites:** [lesson 02](../02-chunking-and-embeddings/), which produces the chunks and vectors this lesson searches.

## Why this matters for the factory

Ask a support index about "error code TS-999" and an embedding model may return three passages about error codes in general. Anthropic's contextual retrieval post uses that example: "An embedding model might find content about error codes in general, but could miss the exact "TS-999" match." Ask the same index "why does the second request cost less" and a keyword search may return nothing at all, because the passage that answers it says "cache read" and "prefix", not "second request" or "cost less".

Factory questions mix both kinds. Engineers paste stack traces, flag names and ticket numbers, and they also ask in their own words. Each retriever on its own is blind to one of the two, so the fix is to run both and combine their results, which is what Anthropic's pipeline does ("Combine and deduplicate results ... using rank fusion techniques") and what the pgvector README recommends: use it "together with Postgres full-text search for hybrid search", and "You can use Reciprocal Rank Fusion or a cross-encoder to combine results."

## Core idea

Two retrievers over the same chunks, each producing a ranked list, fused by rank.

- **Full text** matches words after normalisation (lowercasing, stemming, stopwords dropped) and ranks by how densely the query's terms occur. It wins on identifiers, rare terms and exact phrases.
- **Vector search** ranks by cosine similarity of embeddings. It wins when the query and the passage say the same thing in different words, to the extent the embedder knows they do.
- **Reciprocal rank fusion** gives each chunk `1 / (k + rank)` from every list it appears in and sorts by the sum. Only positions matter, so it needs no calibration between a cosine and a text-search rank.

The exercise keeps both retrievers in one Postgres table: a generated `tsvector` column with a GIN index for full text and a `vector` column with an HNSW index for cosine search. Both live in one database, are written in one transaction and are re-indexed together.

## Mechanics

### Full text in Postgres

`to_tsvector('english', text)` turns a chunk into lexemes with positions: "Caching prompts" becomes `'cach':1 'prompt':2`. The exercise stores it as `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED` with a GIN index, so the column can never drift from the text.

User input goes through `websearch_to_tsquery('english', query)`, chosen because, in the documentation's words, "this function will never raise syntax errors, which makes it possible to use raw user-supplied input for search." Its rules are those of a web search box: unquoted text becomes terms joined by `&`, quoted text becomes terms joined by `<->` (followed by), the word "or" becomes `|`, and a dash becomes `!`. `to_tsquery` on the same input would raise on a stray quote or an unbalanced parenthesis; the stage 03 tests send `"exact phrase" -term OR x`, `it's a cache' OR '1'='1` and `a & b | !c <-> (d:*)` and require results, not exceptions.

The `&` is a problem for questions. A natural-language question rarely has every one of its words in one chunk, so an all-terms match returns little or nothing. The exercise's `text_search` keeps the safe parser and then rewrites its output: the positive terms (words and quoted phrases) are ORed into one query, and each negated term stays an exclusion, `tsv @@ q AND NOT tsv @@ (neg1 | neg2 ...)`. Replacing every `&` with `|` would be wrong in the other direction: `!term` ORed in matches every chunk that lacks the term.

Ranking uses `ts_rank_cd(tsv, q, 32)`. The `cd` is cover density, from Clarke, Cormack and Tudhope's 1999 paper on one- to three-term queries: like `ts_rank`, "except that the proximity of matching lexemes to each other is taken into consideration." It needs positions ("If there are no unstripped lexemes in the input, the result will be zero"), which a stored `to_tsvector` has. The normalisation flag 32 divides the rank by itself plus one, which maps scores into zero to one, but "of course this is just a cosmetic change; it will not affect the ordering of the search results."

### Vector search with pgvector

pgvector adds three distance operators: `<->` for L2, `<#>` for negative inner product and `<=>` for cosine distance. The exercise orders by `embedding <=> query_vec` and reports `1 - distance` as the score. Parameters cross the driver boundary with pgvector-python: `from pgvector.psycopg import register_vector`, then `register_vector(conn)`, and numpy arrays go in and come out as `vector` values.

The index is `CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)`. HNSW is approximate: the README says it "has better query performance than IVFFlat (in terms of speed-recall tradeoff)" at the price of "slower build times and uses more memory." `hnsw.ef_search` is "the size of the dynamic candidate list for search (40 by default)". An HNSW scan returns at most that many rows, so `LIMIT 50` silently returns 40. The exercise raises it per query inside a transaction with `set_config('hnsw.ef_search', ..., true)`; "A higher value provides better recall at the cost of speed." The same limit explains why filtering after the index scan can return fewer rows than asked: the filter runs on the candidates the index already produced.

### Reciprocal rank fusion

Cormack, Clarke and Büttcher's 2009 paper defines the score for a document `d` over a set of rankings `R` as

```
RRF(d) = Σ over r in R of 1 / (k + r(d))
```

where `r(d)` is the 1-based rank of `d` in ranking `r`, and a ranking that does not contain `d` adds nothing. On the constant, the paper says "k = 60 was fixed during a pilot investigation and not altered during subsequent validation", that it "was near-optimal, but that the choice was not critical", and that "The constant k mitigates the impact of high rankings by outlier systems." With `k = 60`, first place is worth 1/61 and tenth place 1/70: being near the top matters, but no single list can dominate.

The sample fuses an invented vector list (cosine scores around 0.8) and an invented full-text list (cover-density scores around 0.1 to 0.3), first by adding raw scores and then by RRF, and checks the arithmetic the stage 03 tests pin.

Sample: `site/samples/m4/03-1.py`.

```python
from retrieval_lab_lessons import rrf, score_sum

vector = [("c7", 0.82), ("c2", 0.80), ("c9", 0.79), ("c4", 0.77)]
text = [("c4", 0.31), ("c5", 0.09), ("c7", 0.05)]

print("score sum:", [(cid, round(s, 3)) for cid, s in score_sum([vector, text])])
fused = rrf([[cid for cid, _ in vector], [cid for cid, _ in text]], k=60)
print("rrf k=60: ", [(cid, round(s, 5)) for cid, s in fused])

filler = [f"f{i:02d}" for i in range(1, 30)]
twice = rrf([[*filler, "both"], [*filler, "both"], ["solo"]])
scores = dict(twice)
print(
    f"30th in two lists {scores['both']:.5f} = 2/90, first in one list {scores['solo']:.5f} = 1/61"
)
```

Output, run on 2026-10-17:

```
score sum: [('c4', 1.08), ('c7', 0.87), ('c2', 0.8), ('c9', 0.79), ('c5', 0.09)]
rrf k=60:  [('c7', 0.03227), ('c4', 0.03202), ('c2', 0.01613), ('c5', 0.01613), ('c9', 0.01587)]
30th in two lists 0.02222 = 2/90, first in one list 0.01639 = 1/61
```

`c5` is second in the full-text list. In the score sum it comes last, behind `c9`, the vector side's third choice, because every vector score is larger than every text score: the sum is decided by which retriever happens to produce bigger numbers. Under RRF, `c5` ties `c2` (1/62 each; the exercise breaks ties by chunk id) and `c7`, near the top of both lists, wins. The last line is the property the tests assert: a chunk ranked 30th by both retrievers (2/90) outranks a chunk ranked first by only one (1/61). Agreement between two independent retrievers is strong evidence; one retriever's favourite is weaker evidence. A test in stage 03 also gives one vector hit a raw score of 999 at rank 30 and checks that it still loses to a text hit at rank 1 with a score of 0.0001.

In the exercise, `hybrid.rrf(lists, k=60)` returns `Ranked(chunk_id, score, rank, ranks)` with the rank from each input list (`None` when absent), and `hybrid.search` fuses the vector top 50 with the full-text top 50.

### Where each side wins on the golden set

The golden set has 16 queries of each kind: `lexical` queries contain an identifier or rare term that appears verbatim in the answer, `conceptual` ones paraphrase without sharing content words, and `factual` ones ask for a stated fact. One lexical query is pinned in the stage 03 tests as found by full text and missed by vector search, and fusion still finds it. The stage also asserts that fused recall@10 is at least that of each side and above one of them.

With the hashing embedder and full text, fused and then reranked (lesson 04), lexical and factual recall@10 are 1.000 and 0.938, and conceptual is 0.250. The hashing embedder is itself lexical, so the two retrievers largely agree, and fusion cannot recover what neither side can see. With bge-small vectors in the live run, hybrid recall@10 overall is 0.740 against 0.656 for hashing, and conceptual recall rises to 0.312 before reranking. Lexical recall with bge-small is 0.969, not 1.000: a real model is better at paraphrase and no better at identifiers, which is why the full-text side stays.

## Common pitfalls

- **Adding raw scores.** Cosine similarity and `ts_rank_cd` live on different scales with different distributions; the sum is decided by whichever is larger. Fuse ranks, or learn a calibrated combination with labelled data.
- **`to_tsquery` on user input.** It raises on ordinary punctuation. Use `websearch_to_tsquery`, or `plainto_tsquery` when operators are not wanted.
- **All terms required.** A question ANDed term by term matches almost nothing. OR the positive terms, keep the negations, and let ranking sort it out.
- **The `ef_search` cap.** An HNSW `LIMIT 50` returns 40 rows by default, and a filter after the scan returns fewer still.
- **Non-deterministic ties.** Equal fused scores are common (1/62 and 1/62 above). Break ties by a stable key or tests will flap.

## What interviewers ask

**Why hybrid search instead of only vectors?**
Embeddings capture paraphrase and miss exact tokens: identifiers, error codes, rare names. Full text is the opposite. Running both and fusing them covers both query kinds; Anthropic's contextual retrieval results improve when contextual BM25 is added to contextual embeddings (a 49% cut in top-20 failures against 35% for embeddings alone).

**Write the RRF formula and explain k.**
`score(d) = Σ_r 1 / (k + rank_r(d))` over the lists that contain `d`, with `k = 60` from Cormack, Clarke and Büttcher, who found it near-optimal and not critical. `k` flattens the curve so that one list's top result cannot dominate: 30th in two lists (2/90) beats first in one (1/61).

**Why not normalise the scores and add them?**
Normalising fixes the range, not the meaning. A cosine of 0.8 and a cover-density rank of 0.3 are not comparable evidence, and their distributions shift per query. Postgres itself says its 0 to 1 normalisation is cosmetic and does not change the order. RRF uses only positions, needs no training data and is hard to break; a learned combination needs labels.

**Your vector search returns 40 rows when you ask for 50. Why?**
pgvector's HNSW scan returns at most `hnsw.ef_search` candidates, 40 by default. Raise it for the query, inside a transaction with `SET LOCAL` or `set_config(..., true)`, and know that higher values cost latency.

## Sources

- [PostgreSQL 17: 12.3. Controlling Text Search](https://www.postgresql.org/docs/17/textsearch-controls.html), sections 12.3.2 Parsing Queries and 12.3.3 Ranking Search Results, checked 2026-10-17
- [pgvector README](https://github.com/pgvector/pgvector), version 0.8.7, sections on distance operators, HNSW, `hnsw.ef_search`, filtering and hybrid search, checked 2026-10-17
- [pgvector-python README](https://github.com/pgvector/pgvector-python), section Psycopg 3, checked 2026-10-17
- Gordon V. Cormack, Charles L. A. Clarke, Stefan Büttcher, [Reciprocal rank fusion outperforms Condorcet and individual rank learning methods](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf), SIGIR 2009, pages 758 to 759, DOI 10.1145/1571941.1572114 (authors' PDF), checked 2026-10-17
- [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval), Anthropic, 2024-09-19, the BM25 discussion and the failure-rate results, checked 2026-10-17
- Course code (repository files, not web sources): stages 02 and 03 in `course/m4-retrieval-lab/README.md` and `tests/test_03_hybrid_retrieval.py`, the live record `course/m4-retrieval-lab/fixtures/live_local_models_run.json`, the lesson helpers in `course/m4-retrieval-lab/lesson_support/src/retrieval_lab_lessons/`
