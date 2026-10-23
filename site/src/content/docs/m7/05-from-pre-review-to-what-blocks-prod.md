---
title: From pre-review to what blocks prod
description: The capstone's live run as evidence, cost per PR and what it buys, how to present a pre-review gate to leadership in terms of speed rather than quality, what to measure once it runs on real pull requests, and the limits you should state before anyone else does.
module: m7
order: 5
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://dora.dev/guides/dora-metrics/
    title: DORA's software delivery performance metrics
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/code-review
    title: Code Review
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/code-review-customize
    title: Customize Code Review
    checked: 2026-10-17
  - url: https://www.helpnetsecurity.com/2026/10/06/github-reviewbench-ai-code-review-benchmark/
    title: GitHub's ReviewBench puts AI code reviewers to the test
    published: 2026-10-06
    checked: 2026-10-17
  - url: https://kodus.io/en/ai-code-review-recall/
    title: AI code review recall
    published: 2026-08-18
    checked: 2026-10-17
  - url: https://codeant.ai/blogs/ai-code-review-benchmark-results-from-200-000-real-pull-requests
    title: AI code review benchmark results from 200,000 real pull requests
    checked: 2026-10-17
---

**Prerequisites:** [lesson 04](../04-blocker-ranking-from-repository-signals/), which defines the blockers and the merge, hold and block verdicts that this lesson turns into numbers for a decision.

## Why this matters for the factory

The capstone ends with something you can show: a gate that ran over twelve pull requests on a real model, with a cost, a time, a verdict per PR and a score against labels. Whether it ever runs on your team's repositories depends on how you present it. Present it as "AI improves code quality" and you start an argument about a word nobody measures. Present it as "a human confirms a ranked report in minutes instead of reading every agent PR cold, and fewer changes come back as rollbacks" and you are talking about lead time and change failure, which leadership already tracks and which you can measure before and after.

This lesson turns the live record into that case: the numbers to quote, the framing, the metrics to watch after launch, and the limits to state up front.

## Core idea

The value of a pre-review gate is that most of what decides a PR's fate (does it apply, do the tests pass, is the migration numbered right, does it have the approvals its paths need) is settled before a human looks, and that the human gets a short, ranked, evidence-carrying report instead of a raw diff. The model reviewer adds findings on top, and its quality is a measured number with known limits.

The case therefore has three parts: what it costs per PR, what it saves per PR, and what you will measure to prove the saving. The live run answers the first; the second is a hypothesis that the report-only month measures, and the run's weaknesses tell you which metrics to watch for the third.

## Mechanics

### The live run, in numbers you can quote

Stage 08 ran the full pipeline on `claude-opus-5-5` with a 0.40 USD budget and 20 turns per PR: apply, test, review, clean, rank, verdict. The aggregate lives in `course/m7-capstone/fixtures/live_review_run.json`, and the sample prints the figures a pitch needs.

Sample: `site/samples/m7/05-1.py`.

```python
from pathlib import Path

from capstone_lessons import live_summary

live = live_summary(Path("course/m7-capstone/fixtures/live_review_run.json"))
verdicts = live["verdicts"]
rows = [
    ("PRs / reviewed by the agent", f"{live['prs']} / {live['reviewed']}"),
    ("total cost, USD", f"{live['total_usd']:.2f}"),
    ("mean cost per reviewed PR, USD", f"{live['usd_mean']:.3f}"),
    ("cost per 100 such PRs, USD", f"{100 * live['usd_mean']:.2f}"),
    ("wall time, s (sequential)", f"{live['wall_seconds']:.0f}"),
    ("median time per PR, s", f"{live['seconds_median']:.1f}"),
    ("merge / hold / block", f"{verdicts['merge']} / {verdicts['hold']} / {verdicts['block']}"),
    ("verdicts equal to the key", f"{live['agree_with_key']} of {live['prs']}"),
    ("findings after cleaning", f"{live['findings']}"),
    ("of them matching no label", f"{live['noise']}"),
    ("precision / recall", f"{live['precision']:.3f} / {live['recall']:.3f}"),
    ("blocker recall", f"{live['blocker_recall']:.2f}"),
    ("failed reviews", f"{live['review_failed']}"),
]
for label, value in rows:
    print(f"{label:<32}{value:>12}")
```

Output, run on 2026-10-23:

```
PRs / reviewed by the agent          12 / 11
total cost, USD                         0.70
mean cost per reviewed PR, USD         0.064
cost per 100 such PRs, USD              6.38
wall time, s (sequential)                131
median time per PR, s                   11.4
merge / hold / block               1 / 3 / 8
verdicts equal to the key           10 of 12
findings after cleaning                   19
of them matching no label                  8
precision / recall              0.579 / 0.917
blocker recall                          0.80
failed reviews                             0
```

Twelve PRs cost 0.70 USD in total. Eleven were reviewed by the agent at a mean of 0.064 USD each, between about 4 and 10 cents per PR, so a hundred PRs of this size cost about 6.38 USD in model spend. The whole run took 131 seconds sequentially; the median PR took 11.4 seconds including applying the patch and running both test suites. Nothing failed: no review needed the retry path, none hit its budget.

On quality, the run cleared the stage's floors (blocker recall at least 0.75, precision at least 0.4) without much room. Of the 19 findings left after cleaning, 11 matched a label: precision 0.579. It found 11 of the 12 labelled issues, recall 0.917, and 4 of the 5 blocker issues, blocker recall 0.80. Ten of the twelve verdicts equal the answer key. For comparison, the recorded reviewer that the offline stages use scores precision 0.6875, recall 0.917 and blocker recall 1.0 after cleaning, so the live model is somewhat noisier and missed one blocker issue that the recorded one caught. The live run's verdict split, one merge, three holds and eight blocks, reflects a fixture seeded with problems and says nothing about how often real PRs block.

### Cost per PR is the easy part

At a few cents per PR, model cost is not the argument. Compare it with the time it buys: one minute of an engineer's attention costs more than a whole review run here. The cost that matters is attention, in both directions: the time a human spends confirming a report, and the time lost to findings that are wrong. Keep cost per PR on the dashboard because it moves when prompts or rules change and because a runaway review is a bug, but lead with time rather than with it.

### How to present it: speed, in the terms leadership already uses

DORA's metrics are a common vocabulary for engineering leadership. Two of them are what a pre-review gate can move. Change lead time is "The amount of time it takes for a change to go from committed to version control to deployed in production", and change fail rate is "The ratio of deployments that require immediate intervention following a deployment", "Likely resulting in a rollback of the changes or a “hotfix” to quickly remediate any issues" (DORA's software delivery performance metrics). A pitch in those terms has three parts:

1. **What it does.** Before a human opens an agent's PR, the gate applies it, runs the tests, checks migration numbering and required approvals, and has a read-only reviewer read the diff against the repository's rules. It produces one ranked report: merge, hold with a reason, or block with a reason.
2. **What it saves.** The human's job on a PR becomes confirming a report rather than reading a diff cold. For holds that means minutes, often without a new commit; for blocks the PR goes back to its author before anyone spends review time. Changes that would have failed after deployment for the reasons the gate checks (a broken test, a duplicated migration, a reused field number caught by the reviewer) stop before merge, which is change fail rate.
3. **What it costs and how you will know.** A few cents and well under a minute per PR on the course's run, and a set of metrics, below, measured for a month before and after, with the honest limits stated.

Avoid two words. "Quality" invites the question "better than whom", and the answer is that the model's findings are less precise than a careful senior reviewer. "Automated review" invites the fear that reviewers are being removed. The gate removes the part of their work that was never judgement, and puts the judgement part first in their queue.

### What to measure after launch

Measure the outcome, not the agent's activity:

- **Time to merge**, from PR opened to merged, per PR class (agent-written, human-written, sensitive paths). This is the lead-time component the gate is supposed to shorten. Watch the median and the tail.
- **Human time per PR**, if you can get it, from first review event to approval. The claim is "minutes to confirm"; check it.
- **Reverts and hotfixes after merge**, within a fixed window such as seven days, split by whether the gate said merge or a human overrode a hold or block. This is change fail rate at PR level.
- **Overrides**, in both directions: PRs merged despite a block (was the block wrong?) and PRs the gate passed that were later reverted (what did it miss?). Each is a candidate label for your eval set.
- **Finding acceptance**, the share of findings after which the author changed the code. Martian's benchmark uses this as its online true-positive signal (CodeAnt's report of it), and GitHub's Copilot experiment reported "the share of review comments judged by an AI model to have prompted code changes" (Help Net Security). It is a cheap precision estimate on real traffic.
- **Cost per PR and failed reviews**, as operational health, with an alert when either jumps.

Run the gate in report-only mode first, posting its verdict without enforcing it, and compare its verdicts with what humans did. That gives you labelled data from your own repository before the gate can block anyone, which is what lesson 01 said the public benchmarks cannot give you.

### The honest limits

- **Four in ten findings are noise.** Precision 0.58 means 8 of the 19 findings matched no planted issue. Every minor-severity finding in the live run was among them. In production, a reviewer whose minor findings are all noise should not post minor findings. Cap or drop them, as Anthropic's example `REVIEW.md` does with "Report at most five Nits per review" (Customize Code Review).
- **The model missed one blocker issue in five.** Blocker recall 0.80 on five blocker labels. The deterministic blockers did not miss anything they check, which is why they gate first and the model is the second line.
- **Twelve planted PRs and two runs.** The labels were written with the fixture and the issues are planted. Two committed runs are not a variance estimate, though both scored blocker recall 0.80 and disagreed with the key on the same two PRs (the first run, `live_review_run_v1.json`, predates the current tool options and rules source), so that miss is stable rather than noise, and it belongs in the deterministic layer: a renamed JSON field without a major version bump can be checked from the changelog and the diff. [M2 lesson 04](../../m2/04-agent-evals/) covered pass^k: the same PR reviewed several times should get the same blocker verdict before you trust any single run.
- **A reviewer that never blocks is cheaper than one that blocks wrongly.** A false block stops a correct change and teaches people to override the gate. That is why Anthropic's managed reviewer is designed so that "A review never approves or blocks the pull request" (Code Review), and why the capstone lets the model block only through blocker-severity findings after cleaning. If your measured false-block rate is not near zero, demote model findings to holds.
- **The gate runs the PR's code.** `go test` and `node --test` execute whatever the patch adds, with the environment of the process that runs the gate. On a learner's machine that is acceptable; in production the gate runs in a sandbox with a scrubbed environment and no network.
- **No finding is not a pass.** The managed service says "A review with no findings doesn't mean your code is error-free or secure" (Code Review). The same holds for this gate.
- **More recall costs more noise.** Kodus measured it: a configuration that found 84 bugs instead of 72 produced 328 false positives instead of 170, and they made it opt-in. Do not raise recall until precision can afford it.

## Common pitfalls

- **Leading with model cost.** Lead with lead time and failed changes.
- **Selling quality.** The numbers do not support it. Sell speed and evidence.
- **Launching in blocking mode.** You get a month of arguments and no labels. Start report-only.
- **Measuring the agent's activity.** Findings posted per PR goes up when the agent gets worse. Measure merges, reverts and overrides.
- **Hiding the limits.** A stakeholder who finds the 0.58 on their own stops trusting the 0.80 too.
- **Treating the fixture's block rate as a forecast.** The PRs were seeded with problems. Your block rate comes from your report-only month.

## What interviewers ask

**How would you justify a pre-review agent to an engineering director?**
In delivery terms: shorter lead time because humans confirm a ranked report instead of reading every diff cold, and a lower change fail rate because broken tests, misnumbered migrations and similar problems stop before merge. Back it with a measured run (on the course's, a few cents and about twelve seconds per PR) and a plan to measure time to merge and reverts before and after.

**What would you measure in the first month?**
Time to merge per PR class, reverts and hotfixes within a week of merge, overrides of the gate in both directions, finding acceptance (code changed after a finding), cost per PR and failed reviews. Run report-only first so humans' decisions become labels.

**Your reviewer has precision 0.58. Is that good enough?**
For holds and attention, possibly; for blocking, no. Four findings in ten are noise, so model findings should only block at blocker severity after hygiene, deterministic signals should do most of the blocking, and categories that are always noise should be dropped. Then measure the false-block rate directly.

**Why not let the agent block PRs whenever it finds something?**
A false block stops correct work and trains people to override the gate. Let facts block, let the model hold, and let humans decide.

## Sources

- [DORA's software delivery performance metrics](https://dora.dev/guides/dora-metrics/), checked 2026-10-17
- [Code Review](https://code.claude.com/docs/en/code-review), Claude Code docs, checked 2026-10-17
- [Customize Code Review](https://code.claude.com/docs/en/code-review-customize), example `REVIEW.md`, Claude Code docs, checked 2026-10-17
- [GitHub's ReviewBench puts AI code reviewers to the test](https://www.helpnetsecurity.com/2026/10/06/github-reviewbench-ai-code-review-benchmark/), Help Net Security, published 2026-10-06, checked 2026-10-17
- [AI code review recall](https://kodus.io/en/ai-code-review-recall/), Kodus (vendor), published 2026-08-18, checked 2026-10-17
- [AI code review benchmark results from 200,000 real pull requests](https://codeant.ai/blogs/ai-code-review-benchmark-results-from-200-000-real-pull-requests), CodeAnt (vendor) on Martian's Code Review Bench, checked 2026-10-17
- Course code and records (repository files, not web sources): the live records `course/m7-capstone/fixtures/live_review_run.json` and `live_review_run_v1.json`; stages 06 and 08 in `course/m7-capstone/README.md`; the lesson helpers in `course/m7-capstone/lesson_support/src/capstone_lessons/`
