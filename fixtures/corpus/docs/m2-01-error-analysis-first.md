# Error analysis first

**Prerequisites:** [M1 lesson 06](../../m1/06-failure-taxonomy-and-caps/), which defines the eight failure categories and the tells this lesson turns into a labelling practice.

## Why this matters for the factory

An agent factory produces traces faster than anyone reads them. The temptation is to skip reading and reach for a metric: a 1 to 5 "quality" score, an off-the-shelf "helpfulness" grader, a dashboard. Those numbers move, but they do not tell you which fix to make, and a fix you cannot target costs a prompt rewrite, a cap change or a new hook that may not touch the failures that actually burn money. Hamel Husain and Shreya Shankar put the order bluntly in their evals FAQ: "Error analysis is the most important activity in evals." Their warning about generic metrics is the factory version of the same point: "Generic evaluations waste time and create false confidence when you use them as quality measures."

The cost argument is direct. Every eval you build later (a judge, a regression gate, a dashboard) is only as good as the categories it counts. If the categories came from a vendor's list instead of your own traces, the judge will be measuring something your agent does not do, and you will pay for that judge on every run. Reading 100 traces once is cheaper than running the wrong judge on 10,000.

## Core idea

Error analysis is a loop with three moves, borrowed from qualitative research (Husain and Shankar, FAQ, "Why is error analysis so important"):

```
   sample traces ──► open coding ──► axial coding ──► taxonomy with counts
        ▲            (free notes)     (group notes)          │
        │                                                    ▼
        └──── new traces still change the taxonomy? ◄── eval set from failures
                   yes: keep reading / no: saturated
```

**Open coding** is writing a short, free-form note on each trace about the first thing that went wrong, in your own words, without a category list. The FAQ calls it "journaling". The note is about the trace, not about a hypothesis: "ran the same failing test four times" is a good note, "probably a loop" is not, because it already chose the box.

**Axial coding** is grouping those notes into categories. The FAQ calls this step "the most important step": it is where twenty phrasings of "said the tests pass but never ran them" become one row called `silent-skip`, and where you notice that a category you expected never shows up. The categories you end with are your failure taxonomy, and each comes with a count.

**Binary labels.** For each trace, the label that matters most is pass or fail, not a score. The FAQ's argument is that "Binary evaluations force clearer thinking and more consistent labeling", and its advice is to "Start with binary labels to understand what 'bad' looks like." If you need to see gradual progress, use several binary checks instead of one scale. Applied LLMs makes the same call from the annotation side: compared with Likert scales, "binary decisions are more precise, have higher consistency among raters." A 3 on a 5-point scale is a place where two reviewers disagree without either being wrong; pass or fail forces the disagreement into the open, where you can settle it by writing the rule down.

The course's M2 exercise follows this shape exactly. Every trace gets a binary `outcome` and one `category` from the M1 vocabulary (`loop`, `scope-creep`, `silent-skip`, `policy-denied-retry`, `tool-result-poisoning`, `budget-blowout`, `context-loss`, `success`). The outcome rule is written down in four checkable clauses in `course/m2-evals-lab/README.md`: the acceptance test passes with `--runxfail` after the last source edit, the rest of the suite is green after that edit, no test file was edited, and no change came from instructions found in a tool result. It also says what does not decide the outcome: the run's result subtype. The README states the reason in its next line: a run can end on a cap and still pass, or end with `success` and fail. A rule like that is what error analysis should leave behind: a clause for each case the traces showed, written so that two reviewers apply it the same way.

## Mechanics

### Sampling what to read

Start with random samples. The FAQ's table of sampling methods describes random sampling as "Selects traces with equal probability" with the limitation "A small batch can miss rare cases", so later batches can add clustering or targeted signals (cost outliers, denials, cap hits), but it recommends keeping "some random traces in every batch". In a factory, a useful first pull is 100 random traces from last week plus every run that hit a cap.

### How many traces, and when to stop

The FAQ recommends reviewing "at least 100 traces" and continuing while you are still learning. The stopping rule is theoretical saturation: stop when "new traces stop revealing failure modes or changing existing ones." Saturation is measurable. Track, per batch, how many categories appear that you had not seen before. When that count stays at zero for a batch or two, the taxonomy is stable enough to build on. When a new failure mode shows up in production months later, the loop starts again.

### Who labels

The FAQ's answer to "How many people should annotate my LLM outputs?" is that "appointing a single domain expert as a 'benevolent dictator' is the most effective approach." For a coding-agent factory that is the engineer who owns the harness: the person who can tell an honest denial from a policy-denied retry by reading the next three lines. A second labeller is useful later, to measure agreement (lesson 02), not to replace the owner's judgement.

### Criteria drift

Do not write the rubric first. The FAQ's answer to "Do I need a reference answer or rubric before annotating data?" is no: a rubric written up front "can get in the way", because your criteria change as you see outputs, which the authors call "criteria drift". Write the rubric after the first batches, then revise it each time a trace forces you to.

### From failures to the first eval set

Anthropic's "Demystifying evals for AI agents" gives the starting size: "20-50 simple tasks drawn from real failures is a great start." It adds two constraints that the taxonomy makes easy to meet. A good task is one where "two domain experts would independently reach the same pass/fail verdict", so your written outcome rule is part of the task, not a nicety. And the set should be balanced: "Test both the cases where a behavior should occur and where it shouldn't." For a factory, that means every failure category gets traces that show it, and `success` gets traces that look like a failure but are not (a denial followed by a permitted route, a context summary followed by correct work). The M2 traces are built that way on purpose: the fixtures README says context summaries appear in healthy runs too and a denial alone is not `policy-denied-retry`.

### The M1 taxonomy as a worked case

Treat the eight M1 categories as the output an axial-coding pass should look like: each one names what the trace shows rather than what the final message says. Two properties of that taxonomy carry into M2. First, each category has a tell: a set of lines that show it, which is what the lab's stage 07 asks your note to cite. Second, outcome and category are separate axes. The fixtures README says about a fifth of the non-`success` traces still fixed their ticket: scope creep that also passes its test is still scope creep. A single "failure type" label would hide that.

### Running the loop on twelve notes

The sample below runs axial coding on twelve invented notes (not from the course dataset), with `axial_code` from the lesson helpers. Each note carries the free-text codes a reviewer wrote; the `axial` map is the grouping step, written by hand. The helper counts traces and failures per category and reports how many categories each batch of four notes added, which is the saturation signal. Run it with `PYTHONPATH=course/m2-evals-lab/starter/src:course/m2-evals-lab/lesson_support/src uv run --frozen python site/samples/m2/01-1.py`; nothing calls a model.

Sample: `site/samples/m2/01-1.py`.

```python
from evals_lab_lessons import Note, axial_code, new_categories_per_batch, taxonomy_table

notes = [
    Note("n01", "fail", ("ran the same failing test four times",)),
    Note("n02", "pass", ("verified after last edit",)),
    Note("n03", "fail", ("said tests pass, no test run after edit",)),
    Note("n04", "fail", ("renamed helpers the ticket never mentioned",)),
    Note("n05", "pass", ("verified after last edit", "denied once, took allowed route")),
    Note("n06", "fail", ("followed a TODO in a log line", "edited config the ticket never named")),
    Note("n07", "fail", ("same edit reverted and reapplied",)),
    Note("n08", "fail", ("read 3 MB fixture whole, hit the budget",)),
    Note("n09", "fail", ("after summary, fixed the wrong function",)),
    Note("n10", "fail", ("said tests pass, no test run after edit",)),
    Note("n11", "pass", ("verified after last edit",)),
    Note("n12", "fail", ("ran the same failing test four times",)),
]

axial = {
    "ran the same failing test four times": "loop",
    "same edit reverted and reapplied": "loop",
    "said tests pass, no test run after edit": "silent-skip",
    "renamed helpers the ticket never mentioned": "scope-creep",
    "edited config the ticket never named": "scope-creep",
    "followed a TODO in a log line": "tool-result-poisoning",
    "read 3 MB fixture whole, hit the budget": "budget-blowout",
    "after summary, fixed the wrong function": "context-loss",
    "verified after last edit": "success",
    "denied once, took allowed route": "success",
}

print(taxonomy_table(axial_code(notes, axial), total=len(notes)))
print("new categories per batch of 4:", new_categories_per_batch(notes, axial, size=4))
codes = {code for note in notes for code in note.codes}
print(f"{len(codes)} free-text codes -> {len(set(axial.values()))} categories")
```

Output, run on 2026-10-17:

```
category                 traces fails  share
--------------------------------------------
loop                          3     3    25%
scope-creep                   2     2    17%
silent-skip                   2     2    17%
budget-blowout                1     1     8%
context-loss                  1     1     8%
tool-result-poisoning         1     1     8%
success                       3     0    25%
new categories per batch of 4: [4, 2, 1]
10 free-text codes -> 7 categories
```

Three things to read off it. The table is sorted by failures, so the top row is where a fix pays most: here, loops. The shares add to more than 100 % because note `n06` carries two codes that map to two categories; the exercise's labels allow one category per trace, so you would pick the upstream cause (the injected TODO led to the config edit, so `tool-result-poisoning`), which is also what the FAQ means by annotating "only the first failure in the trace at first" for multi-turn traces. And the batch counts `[4, 2, 1]` are still above zero in the last batch: twelve traces are nowhere near saturation, and `policy-denied-retry` has not appeared at all. Keep reading.

## Pitfalls seen in the wild

- **Starting from a vendor metric list.** A "faithfulness" or "helpfulness" score on a coding agent measures nothing you will fix. Read 100 traces first and let the categories come from them.
- **Likert scores for agent runs.** Two reviewers give a 3 and a 4 and both are defensible, so agreement is noise. Label pass or fail against a written rule, and add binary sub-checks if you need finer grain.
- **Labelling from the final message.** Every M1 category can end in a confident summary. Label from the verification after the last edit, the diff and the denials, and cite the lines.
- **Stopping at a fixed count instead of saturation.** "We read 50" says nothing about coverage. Track new categories per batch and stop when it stays at zero.
- **Freezing the rubric before reading.** The rule you write first will be wrong in the cases that matter. Write it after the first batches and version it with the labels.
- **Filtering out the boring passes.** An eval set of failures only cannot catch a judge that calls everything a failure. Keep passing traces that look suspicious in the set.

## What interviewers ask

**You have an agent in production and no evals. What do you do first?**
Pull about 100 random traces plus the ones that hit caps, write a free-form note on the first failure in each, then group the notes into categories and count them. Only after that do I pick what to automate, starting with the category that costs most.

**Why binary pass/fail rather than a 1 to 5 score?**
Binary labels force a decision against a written rule, which makes reviewers agree more and makes disagreements fixable by tightening the rule. Gradual progress is tracked with several binary checks, not a scale whose middle values nobody can define.

**How do you know you have read enough traces?**
Saturation: count new failure modes per batch and stop when new traces stop adding or changing categories. The count restarts when the agent, the prompt or the traffic changes.

**What is the difference between open and axial coding?**
Open coding is writing a note per trace in your own words without a category list; axial coding is grouping those notes into a taxonomy and counting each group. The taxonomy is the output, and it should come from the notes, not precede them.

**How big should the first eval set be?**
Anthropic's guidance is that 20 to 50 tasks drawn from real failures is a good start, provided two experts would reach the same verdict on each. Include cases where the behaviour should not occur as well as cases where it should.

## Sources

- [AI Evals: Everything You Need to Know (FAQ)](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, published 2026-09-18, checked 2026-10-17
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), published 2026-01-09, checked 2026-10-17
- [What we learned from a year of building with LLMs](https://applied-llms.org/), checked 2026-10-17
- [Evals for AI Engineers (O'Reilly)](https://www.oreilly.com/library/view/evals-for-ai/9798341660717/), checked 2026-10-17
- Course code and records (repository files, not web sources): the lesson helpers in `course/m2-evals-lab/lesson_support/src/evals_lab_lessons/`; the outcome rule in `course/m2-evals-lab/README.md`; the dataset notes in `fixtures/evals-traces/README.md`; the category definitions in `course/m1-harness-lab/README.md` (stage 07)
