---
title: Citations, faithfulness and agentic retrieval
description: A prompt that numbers its sources and demands a citation per sentence, a refusal decided before the model is called when retrieval support is below a floor, a mechanical check for uncited sentences and invented source numbers, what that check cannot prove, the course's live answer run, and retrieval as a tool inside an agent loop.
module: m4
order: 6
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:fastembed": "0.9.0"
  "pypi:pgvector": "0.5.1"
  "model:default": claude-opus-5-5
sources:
  - url: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
    title: Effective context engineering for AI agents
    published: 2025-09-29
    checked: 2026-10-17
  - url: https://hamel.dev/blog/posts/evals-faq/
    title: "AI Evals: Everything You Need to Know"
    published: 2026-09-18
    checked: 2026-10-17
---

**Prerequisites:** [lesson 05](../05-retrieval-metrics-and-golden-sets/), which measures whether the right chunks reach the prompt this lesson builds.

## Why this matters for the factory

Five good chunks in the prompt do not guarantee a good answer: the model can answer from what it already believes, blend two sources into a claim neither makes, cite source 3 for a sentence that came from source 1, or cite a source 7 that was never given. In a factory, where an agent's answer becomes a config change, a ticket reply or a runbook step, a claim nobody can trace is a liability.

Three things make an answer checkable. Every sentence points at a numbered source, so a reviewer, or a program, can look it up. There is a defined way to say "the sources do not answer this", so the model has an alternative to guessing. And the decision to refuse does not rest only with the model: when retrieval found nothing strong, the pipeline refuses before it spends a model call. This lesson builds those three and then looks at the other shape retrieval can take, as a tool an agent calls in a loop.

## Core idea

Treat the answer step as a contract with a checker.

- **Assemble.** Number the retrieved chunks `[1]` to `[n]`, label each with its chunk id, and instruct the model to answer only from them, to cite every sentence as `[n]`, and to reply with one exact refusal sentence when no source supports an answer.
- **Gate.** Before calling the model, count the chunks whose reranker score clears a support floor. If fewer than `min_support` do, refuse without a call.
- **Check.** Split the reply into sentences, count those without a valid marker, and list any marker outside `1..n`. Those counts are logged and tested; they do not depend on a judge.
- **Then judge.** Whether a cited source actually supports its sentence is a separate, harder question, for a validated judge or a human.

## Mechanics

### The prompt

Stage 06's `answer.assemble(query, chunks, *, scores=None, min_support=1, floor=SUPPORT_FLOOR)` returns a `Draft(prompt, citations, refused)`. The prompt states three rules (answer only from the numbered sources, cite every sentence as `[n]`, reply exactly `I cannot answer from the sources.` when none supports an answer), then the question, then the sources as `[i] <chunk_id>` followed by the chunk text. `citations` holds the chunk ids in the same order, which is how a marker in the reply maps back to a passage, a document and character offsets.

Numbers, not chunk ids, go into the reply because short markers are easy for a model to place and easy for a regex to find; the mapping lives in the program. The exact refusal string matters for the same reason: a program can recognise it, where "I'm not sure the documents cover this" needs interpretation.

### Refusing before the model

The model is not the only place to refuse, and not the cheapest. `assemble` refuses (an empty prompt, `refused=True`) when fewer than `min_support` chunks score at least the floor, and `answer.run` then returns the refusal with no model call and zero cost.

The floor depends on the reranker. The exercise's `SUPPORT_FLOOR = 4.0` is a BM25 score from the lexical reranker, chosen from measurements on the course corpus: off-corpus questions top out between 0 and 3.2 (their stopwords still match something), the median golden query tops out at about 11, and the weakest golden query tops out at 3.86 and therefore refuses. The stage 06 tests pin both sides: six off-corpus questions refuse on the real index, and 47 of the 48 golden queries clear the floor. One golden query refused is the price of not answering six questions the corpus cannot answer. A cross-encoder scores logits on a different scale, so swapping the reranker means measuring a new floor the same way.

### Checking the reply

`answer.check(text, citations)` returns `Faithfulness(cited, uncited_claims, refused)`: the valid source numbers used, the number of sentences without a valid marker (the refusal sentence excepted), and whether the reply refused. A marker outside `1..n` is not a citation; its sentence counts as uncited and `answer.invalid_citations` lists the number. The sample runs the lesson helpers' small version of the same rules on invented replies against five sources.

Sample: `site/samples/m4/06-1.py`.

```python
from retrieval_lab_lessons import toy_check

answers = {
    "cited": "Hits cost a tenth of the input price [2]. Writes cost more [1][3].",
    "one uncited": "Hits cost a tenth of the input price [2]. This makes caching always worth it.",
    "out of range": "Hits cost a tenth of the input price [7].",
    "refusal": "I cannot answer from the sources.",
}
for name, text in answers.items():
    print(f"{name:<13} {toy_check(text, sources=5)}")
```

Output, run on 2026-10-17:

```
cited         {'sentences': 2, 'cited': [1, 2, 3], 'invalid': [], 'uncited': 0, 'refused': False}
one uncited   {'sentences': 2, 'cited': [2], 'invalid': [], 'uncited': 1, 'refused': False}
out of range  {'sentences': 1, 'cited': [], 'invalid': [7], 'uncited': 1, 'refused': False}
refusal       {'sentences': 1, 'cited': [], 'invalid': [], 'uncited': 0, 'refused': True}
```

In the second reply, "This makes caching always worth it." is the kind of sentence a model adds from its own beliefs, and the check catches it only because it has no marker. The third cites a source that does not exist; a check that only counted markers would have passed it.

Sentence splitting is where this check gets fragile. The exercise splits after `.`, `!` or `?` followed by whitespace, or at a line break, and a marker that opens a sentence belongs to the one before. Abbreviations break that rule: the course's live run produced an answer that quoted an abbreviated title followed by a name, and the splitter cut it twice, counting two uncited "claims" that were fragments of one cited sentence. A fix commit added an abbreviation list (`Mr.`, `Mme.`, `e.g.` and others), after which the same text counts one. Read the flagged sentences before trusting `uncited_claims`.

### What the check cannot prove

A marker says which source the model claims to use, not that the source supports the sentence. "Writes cost more [1][3]" passes the check whether or not sources 1 and 3 say anything about writes. Verifying support means reading the cited passage against the sentence: a human, an entailment model, or an LLM judge. The evals FAQ's order applies again: debug retrieval with IR metrics first, "then tackle generation quality using properly validated LLM judges", and validated means measured against human labels, as [M2](../../m2/02-judges-and-agreement/) does. The mechanical check is the floor under that: cheap, deterministic, run on every answer.

### The live answer run

Stage 09 sends three golden queries, one of each kind, through `answer.sources` (hashing embedder, lexical reranker, MMR, top 5), `answer.assemble` and `claude-opus-5-5` through `claude_agent_sdk.query` with `tools=[]`, `max_turns=1`, `setting_sources=[]` and `max_budget_usd=0.05`. The test passes when each answer either refuses or cites a chunk that holds the query's anchor, no answer cites a number it was not given, and the three cost at most $0.20 together. The sample reads the committed record, aggregates only.

Sample: `site/samples/m4/06-2.py`.

```python
from pathlib import Path

from retrieval_lab_lessons import live_answer_summary

live = live_answer_summary(Path("course/m4-retrieval-lab/fixtures/live_answer_run.json"))
print(
    f"model {live['model']}, cap {live['limit_usd']} USD per answer, floor {live['support_floor']}"
)
print(f"{live['answers']} answers ({', '.join(live['kinds'])}), refused {live['refused']}")
print(f"cite a relevant chunk: {live['cite_relevant']}/{live['answers']}")
print(
    f"citations {live['citations']}, invalid {live['invalid']}, uncited sentences {live['uncited']}"
)
print(f"cost {live['cost_usd']} USD of {live['max_total_usd']} allowed")
```

Output, run on 2026-10-23:

```
model claude-opus-5-5, cap 0.05 USD per answer, floor 4.0
3 answers (conceptual, factual, lexical), refused 0
cite a relevant chunk: 3/3
citations 6, invalid 0, uncited sentences 1
cost 0.0986 USD of 0.2 allowed
```

All three answers cleared the floor, none refused, all three cited a chunk containing the anchor, and no answer invented a source number. The one uncited sentence is the splitter artefact described above, in the lexical answer. The run cost $0.099. This is three answers on one model: a demonstration that the contract and the checker work end to end, not a measurement of faithfulness. The refusal path is covered by the offline tests, not by this run.

### Retrieval as a tool

Everything so far is a fixed pipeline: one query in, top 5 out, one model turn. The other shape gives the model the search itself. Anthropic's context engineering post describes agents that "maintain lightweight identifiers (file paths, stored queries, web links, etc.)" and load data with tools at runtime. For an index, that means exposing `search(query)` as a tool that returns chunk ids, heading paths and short snippets, plus `read(chunk_id)` for the full text, and letting the agent search, read, rephrase and search again until it can cite.

Vocabulary gaps are the failure kind a loop addresses best: an agent that reads a near miss can rewrite its query in the document's words, which is the `query-rewrite` fix stage 07 lets you name. The price is the one the post states: "runtime exploration is slower than retrieving pre-computed data". Each search is a model turn plus a tool call. Run it inside the M1 harness with turn and budget caps ([M1 lesson 01](../../m1/01-harness-is-loop-plus-policy/)), keep the citation contract (the agent's final answer still cites chunk ids it read), and measure it with the same golden set: recall of the chunks the agent read, turns per question and cost per question.

The two shapes combine. A fixed pipeline answers most questions in one turn; when it refuses, an agent loop with the same index and a small budget can try rephrasings before the system gives up. Claude Code's hybrid of up-front context plus tools is the same idea applied to code.

## Common pitfalls

- **Citations nobody checks.** A marker is a claim. Count uncited sentences and invalid numbers on every answer, and sample answers for a support judge.
- **Refusal left to the model alone.** A model shown weak sources may answer anyway, and an instruction cannot guarantee it will not. Gate on retrieval scores before the call.
- **A floor copied across rerankers.** BM25 scores and cross-encoder logits are different scales. Measure the floor on off-corpus and golden queries for each reranker.
- **Naive sentence splitting.** Abbreviations, decimals and quotes split sentences that are one claim. Read flagged answers before trusting the count.
- **Agent loops without caps.** A search loop that does not find the answer keeps searching. Cap turns and budget, and log every query it tried.

## What interviewers ask

**How do you make a RAG answer verifiable?**
Number the sources, require a citation per sentence, and define an exact refusal sentence. Then check mechanically: every sentence has a valid marker, no marker points outside the given sources. In the course's live run, three of three answers cited a chunk containing the answer, with no invented source numbers, for $0.085.

**When should the system refuse, and who decides?**
The pipeline decides first: if fewer than a minimum number of retrieved chunks clear a support floor, refuse without calling the model. The floor is measured per reranker; in the course a BM25 floor of 4.0 refuses six off-corpus questions and lets 47 of 48 golden queries through. The model can still refuse with the exact sentence when the sources do not answer.

**Does a citation prove the answer is faithful?**
No. It says which source the model claims to use. Support needs reading the source against the sentence: a human, an entailment model or a validated LLM judge. The mechanical check catches missing and invented citations, which is cheap and deterministic, and leaves support to the judge.

**Fixed pipeline or agentic retrieval?**
A fixed pipeline for volume and latency: one search, one turn, measurable recall. An agent loop when queries are vague or phrased unlike the documents, since it can rephrase after reading a near miss; it costs turns, so cap it. One workable design runs the pipeline first and falls back to a capped agent loop when the pipeline refuses.

## Sources

- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), Anthropic Engineering, 2025-09-29, section Context retrieval and agentic search, checked 2026-10-17
- [AI Evals: Everything You Need to Know](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, 2026-09-18, questions "How should I approach evaluating my RAG system?" and "Is RAG dead?", checked 2026-10-17
- Course code (repository files, not web sources): stages 06, 07 and 09 in `course/m4-retrieval-lab/README.md` and their tests, the live record `course/m4-retrieval-lab/fixtures/live_answer_run.json`, the lesson helpers in `course/m4-retrieval-lab/lesson_support/src/retrieval_lab_lessons/`
