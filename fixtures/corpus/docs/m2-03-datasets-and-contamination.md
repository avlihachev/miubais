# Datasets and contamination

**Prerequisites:** [lesson 02](../02-judges-and-agreement/), which validates a judge against human labels; this lesson is about where those labels come from and how to keep them honest.

## Why this matters for the factory

Every eval number in a factory is a statement about a dataset. "The judge is trusted" means trusted on this labelled set; "the new prompt raises the pass rate by 4 points" means on these tickets. If the set does not look like production traffic, the number describes a different factory. If the set leaked into the thing being measured, the number describes memory. In both cases the decision it feeds (ship the prompt, keep the judge, raise the cap) is made on a figure that will not hold in production, and you find out from the cost line weeks later.

Datasets are also the slowest asset to rebuild. Labels take hours of expert reading; a contaminated test set cannot be un-seen by the people who tuned against it. So a factory treats its golden sets the way it treats a database schema: versioned, hashed, with a record of who may read which part and when.

## Core idea

A **golden set** is a fixed collection of inputs (here, agent traces) with labels written by a domain expert against a written rule, plus the rule itself. It has three jobs, and each needs its own slice:

```
golden set (labelled, versioned, hashed)
 ├── train  10-20 %   may appear in prompts as examples
 ├── dev    40-45 %   iterate against: prompt edits, model choice
 └── test   40-45 %   check once, after the changes are done
```

The split sizes are the FAQ's for judge development (Husain and Shankar, "How many examples do I need for an eval?"): 10 to 20 % "for train examples that may appear in the prompt", 40 to 45 % dev, 40 to 45 % test, with roughly 30 to 50 pass and 30 to 50 fail examples in both dev and test. Eugene Yan's "Product Evals in Three Simple Steps" uses a simpler cut, aligning on 75 % and holding out "the remaining 25% as the test set". The numbers differ; the principle does not. The test slice measures generalisation only as long as no decision was made by looking at it. The FAQ is explicit that overfitting to dev happens even without copying: "This is overfitting, and it can happen even if you never put the dev examples directly in the prompt."

The set must also look like production. Applied LLMs: "the data we test our systems on during development should mirror what the systems will face in production", and it suggests comparing lengths, formats and semantic clusters between the two periodically. Anthropic adds balance: "Test both the cases where a behavior should occur and where it shouldn't" (Demystifying evals for AI agents).

## Mechanics

### Sampling into the set

Start from random samples, as lesson 01 did, then fill gaps on purpose. Stratify by the labels you will report on: category and outcome. If one category is 10 % of traffic and your test slice has three examples of it, its per-category count moves by a third when one trace flips. The FAQ lists stratified sampling among its more advanced sampling methods and keeps "some random traces in every batch" so the set does not drift toward only what you already know to look for.

Stratify on a third axis when the data has groups: the ticket, the repository, the user. Two runs of the same ticket share a prompt, a file layout and often a fix. If one run is in dev and the other in test, the test score partly measures how well the prompt remembers that ticket. Split by group first, then stratify within groups.

### Synthetic data and the surface-pattern trap

When production traces are scarce, generate. The FAQ's position is that "A structured approach using dimensions produces far better synthetic data for testing LLM applications": define the dimensions that vary (in a coding-agent factory: repository, ticket type, failure mode, where an injected instruction hides), "Write 20 tuples by hand", then generate tuples and turn each into an input in two separate steps.

The trap is that a generator writes each category from a template, and templates leave fingerprints: a fixed closing sentence for success, a fixed marker for compaction, a result subtype that always goes with one failure. A judge (or a regex) that keys on the fingerprint scores well on the synthetic set and badly on real traffic. The course's own dataset is synthetic and carries a guard for exactly this. `tools/miubais/tests/test_evals_traces.py` runs a keyword baseline: one regular expression per category, keyed on the most obvious surface phrase or result subtype, first match wins, default `success`. On the 200 traces it labels 0.565 of categories correctly, and the test fails if that ever exceeds 0.58 or moves away from 0.565. The fixtures README states the intent: no category has a fixed phrase, closing line or result subtype, and context summaries, denials and cap hits appear in healthy runs too.

Read 0.565 as a floor, not a target. With 60 of 200 traces in `success` (fixtures README) and a regex for the easy cases, more than half the labels come for free. A judge whose category accuracy is near that floor has learned keywords. This is one reason the trust gate from lesson 02 uses kappa, which removes chance agreement, rather than raw accuracy.

### Contamination and leakage

Leakage is anything that lets the measured system see the answer.

- **Examples in the prompt.** Train-slice examples in a judge prompt are fine; dev or test examples there turn the score into a lookup. Keep the slice of every example you paste into a prompt in the dataset manifest.
- **Tuning on test.** Every look at test results that changes a prompt moves test into dev. Check test once per release of the judge or prompt, and if you must iterate again, label a fresh test slice.
- **Shared state between trials.** Anthropic's evals post warns that "Shared state can also artificially inflate performance", with the example of Claude examining git history from previous trials. For coding agents, give every trial a fresh worktree and keep answer keys out of it. The M2 lab keeps its keys in plaintext under the exercise's `tests/` on an honour system; an agent run inside that tree could read them, which is why a real harness evaluates in a workspace that does not contain them.
- **Public answers.** "Eval awareness in Claude Opus 4.6's BrowseComp performance" reports that "answers leak onto the public web through academic papers, blog posts, and GitHub issues", found nine straightforward contamination cases among 1,266 problems, and describes the model identifying the benchmark, then locating and decrypting its answer key. Its recommendation is to "treat eval integrity as an ongoing adversarial problem rather than a design-time concern."
- **Familiar problems.** "Designing AI-resistant technical evaluations" describes a take-home that stopped separating strong candidates from strong models, partly because some tasks resembled work where "Claude has substantial training data to draw on". The replacement works because it "simulates novel work". For your own evals: tasks copied from public repositories or popular tutorials measure recall; tickets from your own codebase measure the factory.

### Versioning with hashes

A score without a dataset version cannot be compared with anything. Store, next to every recorded score: a hash of the split manifest (which ids are in which slice), a hash of the labels file, the version of the label rule, and the judge or prompt version. When a label is corrected, the labels hash changes, which tells a gate that compares against a stored baseline that the baseline needs recomputing, rather than reporting the change as a drop.

The sample makes a stratified split with the lesson helpers `stratified_split`, `split_counts` and `manifest_hash`. The 200 ids are placeholders (`x001` to `x200`), assigned to categories only so that the totals match the dataset's published distribution of 60 `success` and 20 of each other category (fixtures README); no trace id is paired with its gold label. Run it with `PYTHONPATH=course/m2-evals-lab/starter/src:course/m2-evals-lab/lesson_support/src uv run --frozen python site/samples/m2/03-1.py`; nothing calls a model.

Sample: `site/samples/m2/03-1.py`.

```python
from evals_lab_lessons import manifest_hash, split_counts, stratified_split

published = {"success": 60} | {
    c: 20
    for c in (
        "loop",
        "scope-creep",
        "silent-skip",
        "policy-denied-retry",
        "tool-result-poisoning",
        "budget-blowout",
        "context-loss",
    )
}
strata, i = {}, 0
for category, count in published.items():
    for _ in range(count):
        i += 1
        strata[f"x{i:03d}"] = category

fractions = {"train": 0.2, "dev": 0.4, "test": 0.4}
splits = stratified_split(strata, fractions, seed=17)
print(split_counts(splits, strata))
print("manifest sha256:", manifest_hash(splits)[:16])
again = stratified_split(strata, fractions, seed=17)
print("same seed, same manifest:", manifest_hash(again) == manifest_hash(splits))
overlap = set(splits["train"]) & (set(splits["dev"]) | set(splits["test"]))
print("ids in train and in dev/test:", len(overlap))
```

Output, run on 2026-10-17:

```
stratum                 train    dev   test
-------------------------------------------
budget-blowout              4      8      8
context-loss                4      8      8
loop                        4      8      8
policy-denied-retry         4      8      8
scope-creep                 4      8      8
silent-skip                 4      8      8
success                    12     24     24
tool-result-poisoning       4      8      8
total                      40     80     80
manifest sha256: d9e279d8abe57445
same seed, same manifest: True
ids in train and in dev/test: 0
```

Every category keeps its share in every slice, so the test slice has eight examples of each failure mode rather than whatever a random cut produced. The seed makes the manifest reproducible, and its hash is the identifier you store with each score. Two limits are worth saying out loud. Eight examples per category in test still means one flip moves that category's rate by 12.5 points. And the split stratifies on category only: on the real dataset, where the 200 traces come from ten tickets, a production split would group by ticket first, as the sampling section above explains.

## Pitfalls seen in the wild

- **One set for everything.** Iterating the prompt and reporting on the same traces reports memory. Keep a test slice you check once per release.
- **Random splits over grouped data.** Runs of one ticket in both dev and test inflate test. Split by ticket or repository, then stratify inside.
- **Synthetic data with fingerprints.** A generator that phrases each category the same way trains judges on phrases. Run a keyword baseline on the set and keep it low.
- **Answer keys inside the agent's workspace.** An agent with `Read` and `Grep` will find them. Evaluate in a fresh worktree without keys or history from other trials.
- **Benchmarks copied from public sources.** Public tasks may be in training data or on the web with answers. Build tasks from your own tickets.
- **Unversioned labels.** A corrected label silently changes the baseline. Hash the manifest and the labels file and store both with every score.

## What interviewers ask

**How do you split a labelled set for developing an LLM judge?**
A small train slice for prompt examples, a dev slice to iterate against, and a test slice checked once, roughly 10 to 20 % and 40 to 45 % each, with enough passes and fails in dev and test. Stratify by the labels you report on and group by ticket so near-duplicates do not straddle the split.

**What is the risk with synthetic eval data?**
Generators leave surface patterns, so the set can be labelled by keywords and a judge that scores well has learned the template, not the behaviour. Generate from explicit dimensions, mix in real traces, and keep a keyword baseline on the set to prove the labels need reading.

**Give three ways an eval can be contaminated.**
Test examples used as prompt examples or used to tune the prompt, shared state between trials such as git history or answer files in the agent's workspace, and answers available in training data or on the web. Each inflates scores without any change in real capability.

**How do you version an eval dataset?**
Hash the split manifest and the labels file, version the label rule, and store those identifiers with every score. A changed hash means a new baseline, not a regression.

**Your test score is much lower than dev. What happened?**
Most often the prompt was overfit to dev through repeated iteration, or the dev and test slices differ, for example because groups were split unevenly. Read the test disagreements, check the split, and label a fresh test slice before the next round.

## Sources

- [AI Evals: Everything You Need to Know (FAQ)](https://hamel.dev/blog/posts/evals-faq/), Hamel Husain and Shreya Shankar, published 2026-09-18, checked 2026-10-17
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), published 2026-01-09, checked 2026-10-17
- [Designing AI-resistant technical evaluations](https://www.anthropic.com/engineering/AI-resistant-technical-evaluations), published 2026-01-21, checked 2026-10-17
- [Eval awareness in Claude Opus 4.6's BrowseComp performance](https://www.anthropic.com/engineering/eval-awareness-browsecomp), published 2026-03-06, checked 2026-10-17
- [Product Evals in Three Simple Steps](https://eugeneyan.com/writing/product-evals/), Eugene Yan, published 2025-11-23, checked 2026-10-17
- [What we learned from a year of building with LLMs](https://applied-llms.org/), checked 2026-10-17
- Course code and records (repository files, not web sources): the lesson helpers in `course/m2-evals-lab/lesson_support/src/evals_lab_lessons/`; the keyword baseline in `tools/miubais/tests/test_evals_traces.py`; the dataset notes in `fixtures/evals-traces/README.md`; the answer-key layout in `course/m2-evals-lab/README.md`
