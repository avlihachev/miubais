---
title: Evals for code agents
description: What evaluating a coding or pre-review agent takes, from finding precision and recall against a labelled PR set and tests, build and lint as deterministic verify gates, to cost per PR, time-to-merge, mining labels from history, and the SWE-bench Verified lesson on broken and contaminated tasks.
module: m2
order: 6
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
    title: Demystifying evals for AI agents
    published: 2026-01-09
    checked: 2026-10-17
  - url: https://arxiv.org/abs/2310.06770
    title: "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?"
    published: 2023-10-10
    checked: 2026-10-17
  - url: https://web.archive.org/web/20260101233457/https://openai.com/index/introducing-swe-bench-verified/
    title: Introducing SWE-bench Verified (OpenAI, archived copy)
    published: 2024-08-13
    checked: 2026-10-17
  - url: https://web.archive.org/web/20261015182204/https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
    title: Why SWE-bench Verified no longer measures frontier coding capabilities (OpenAI, archived copy)
    published: 2026-02-23
    checked: 2026-10-17
  - url: https://github.com/rjust/defects4j
    title: rjust/defects4j (README)
    checked: 2026-10-17
  - url: https://dora.dev/guides/dora-metrics/
    title: DORA's software delivery performance metrics
    checked: 2026-10-17
---

**Prerequisites:** [lesson 05](../05-ci-gating-and-tracking/), which turns eval results into a CI gate; this lesson decides what a gate for a code-review agent should measure.

## Why this matters for the factory

The capstone of this course (M7) is a pre-review agent: it reads a pull request on a Go and TypeScript repository, post findings, and say what blocks the change from going to production. In a factory that agent sits between the coding agents and the merge button, so its errors have two prices. A missed blocker ships a bug that a human reviewer was told not to worry about. A false alarm costs a human the time to dismiss it, and enough false alarms teach people to ignore the agent, at which point it costs money and catches nothing. Both show up in precision and recall against PRs whose real problems are known.

Coding agents have one advantage over most agents: much of their output can be checked by running it. Anthropic's evals post: "Deterministic graders are natural for coding agents because software is generally straightforward to evaluate: does the code run and do the tests pass?"

## Core idea

A code agent's eval has three layers, cheapest first:

| layer | measures | data, cadence |
| --- | --- | --- |
| verify gates | build, tests, lint, types | deterministic, every PR |
| findings vs labels | precision, recall by severity; blocker recall first | labelled PR set, every change to the review agent |
| lagging metrics | cost per PR, time-to-merge, reverts after merge | production, weekly |

**Verify gates** are the SWE-bench idea applied to your own tree. SWE-bench (Jimenez et al., arXiv:2310.06770) built its tasks from "real GitHub issues and corresponding pull requests", and grades by tests; OpenAI's SWE-bench Verified post describes the check: "the model's generated patch is applied to the codebase and then the FAIL_TO_PASS and PASS_TO_PASS unit tests are executed. If the patch can be applied successfully and all of the tests pass, then the proposed solution is considered to have successfully resolved the issue." Anthropic summarises the same rule: "a solution passes only if it fixes the failing tests without breaking existing ones." For a review agent the gate runs on the patched tree and its result is evidence the agent must cite, not a verdict it is allowed to contradict.

**Findings versus labels** is where the review agent itself is graded. Precision is the share of reported findings that match a labelled issue; recall is the share of labelled issues the agent found. Report both per severity, because a review agent with high recall on style nits and low recall on blockers fails at its main job, and an aggregate F1 hides that.

**Lagging metrics** tell you whether the agent changed anything that matters, but too late and too noisily to gate a PR on. Cost per PR is known immediately; time-to-merge and post-merge reverts arrive days or weeks later. DORA defines change lead time as "The amount of time it takes for a change to go from committed to version control to deployed in production" and change fail rate as "The ratio of deployments that require immediate intervention following a deployment." A review agent should move both in the right direction; if it does not, the eval set is measuring the wrong thing.

## Mechanics

### Verify gates as deterministic graders

Anthropic's post describes how coding evals usually combine graders: "coding evaluations typically rely on unit tests for correctness verification and an LLM rubric for assessing overall code quality", and its example task config lists a static analysis grader with `commands: [ruff, mypy, bandit]`. For a Go and TypeScript repository the same layer is the repository's own build, tests, vet or lint, and type check, run on the patched tree in a clean checkout. Three practical rules:

- **Run what CI runs.** A gate that uses different commands from the repository's CI disagrees with it, and the disagreement becomes a false finding.
- **Isolate every run.** Shared caches and leftover worktrees produce failures that belong to the environment. Lesson 05's infrastructure-noise numbers apply here unchanged.
- **Keep gate results apart from findings.** "Tests fail on the patched tree" is a fact the agent reports; whether a failing test is a blocker is a judgment the agent ranks. Score them separately.

### Precision and recall of findings

To score a finding you must decide when it matches a label. The helper `match_findings` matches on PR and file and accepts a line within a tolerance (3 lines by default), pairing each label with at most one finding, the nearest. `review_scores` then counts, per severity, reported findings that matched (precision side) and labelled issues that were found (recall side), plus an `all` row. The sample scores an invented set of nine findings against eight labels on four PRs. Run it with `PYTHONPATH=course/m2-evals-lab/starter/src:course/m2-evals-lab/lesson_support/src uv run --frozen python site/samples/m2/06-1.py`; nothing calls a model.

Sample: `site/samples/m2/06-1.py`.

```python
from evals_lab_lessons import Finding, review_scores, review_table

labels = [
    Finding("pr-101", "internal/billing/charge.go", 88, "blocker"),
    Finding("pr-101", "internal/billing/charge.go", 140, "minor"),
    Finding("pr-102", "web/src/cart/total.ts", 31, "blocker"),
    Finding("pr-102", "web/src/cart/total.ts", 77, "major"),
    Finding("pr-103", "cmd/worker/main.go", 12, "major"),
    Finding("pr-103", "internal/queue/retry.go", 54, "blocker"),
    Finding("pr-103", "internal/queue/retry.go", 99, "minor"),
    Finding("pr-104", "web/src/auth/session.ts", 20, "major"),
]
reported = [
    Finding("pr-101", "internal/billing/charge.go", 90, "blocker"),
    Finding("pr-101", "internal/billing/charge.go", 200, "minor"),
    Finding("pr-102", "web/src/cart/total.ts", 31, "blocker"),
    Finding("pr-102", "web/src/cart/total.ts", 33, "blocker"),
    Finding("pr-102", "web/src/cart/total.ts", 76, "minor"),
    Finding("pr-103", "internal/queue/retry.go", 61, "blocker"),
    Finding("pr-103", "cmd/worker/main.go", 12, "major"),
    Finding("pr-104", "web/src/auth/session.ts", 5, "minor"),
    Finding("pr-104", "web/src/api/client.ts", 44, "minor"),
]
print(review_table(review_scores(reported, labels, tolerance=3)))
```

Output, run on 2026-10-17:

```
severity   reported  true labelled found precision recall    f1
---------------------------------------------------------------
blocker           4     2        3     2      0.50   0.67  0.57
major             1     1        3     2      1.00   0.67  0.80
minor             4     1        2     0      0.25   0.00  0.00
all               9     4        8     4      0.44   0.50  0.47
```

Blocker precision is 0.50 because one blocker was reported twice (lines 31 and 33 of `total.ts`, a duplicate) and one was reported seven lines away from the labelled line in `retry.go`, which counts as a false positive and a miss at once. Major recall is 0.67 although only one finding was reported as major: the issue at line 77 of `total.ts` was found but reported as `minor`. This helper credits the match on the recall side and puts it in the reported severity on the precision side; a stricter scorer would also require the severity to agree, and you should decide which rule you want before you compare two agents. The minor row shows the agent's noise: one useful minor finding out of four.

Three decisions hide in every such table and belong in the eval's README: the matching rule (file, line window, or a judge that decides whether two descriptions are the same issue), how duplicates count, and whether severity must agree. Change any of them and every number moves.

### Building a labelled PR set from history

A labelled PR is a patch plus the list of real issues in it, with file, line and severity. Write the labels from evidence. Sources in a repository's own history:

- **Bug-fix commits mined backwards.** Take a commit that fixes a bug, find the commit that introduced the faulty lines, and use that earlier PR as a test case whose blocker is the line later fixed. Defects4J is the long-running example of this discipline; its bugs must have an "Issue filed in the corresponding issue tracker", be "Fixed in a single commit", be "Minimized" (the maintainers "manually pruned out irrelevant changes in the commit (e.g., refactorings or feature additions)"), and have "A triggering test exists that failed before the fix and passes after the fix".
- **Revert commits.** A revert names the PR that broke something. The reverted PR is a labelled case with at least one blocker, and the revert message often says which.
- **Review threads.** Comments that led to a code change before merge are findings a human made; comments that were resolved without a change are weaker labels.
- **Planted issues.** For coverage of rare categories (a stale migration number, a missing proto field), plant them in otherwise clean PRs, as the M7 capstone's fixtures do.

Have two people label a sample independently and compute kappa on severity, as lesson 02 did for categories, before trusting the set. Include clean PRs too: a review agent that never says "nothing blocks this" cannot be scored on precision at the PR level.

### The SWE-bench Verified lesson

SWE-bench Verified shows both failure modes of a labelled set: tasks that cannot be solved and tasks the model has already seen. OpenAI's 2024 post introducing SWE-bench Verified listed the problems with the original set: unit tests that "are often overly specific, and in some cases are even unrelated to the issue", issue descriptions that are "underspecified", and environments that are "sometimes difficult to reliably set up". With "93 software developers experienced in Python" it annotated 1,699 samples, and the process "resulted in 68.3% of SWE-bench samples being filtered out due to underspecification, unfair unit tests, or other issues", leaving 500 verified samples. GPT-4o's score on the best scaffold went to "33.2% on SWE-bench Verified, more than doubling its score of 16% on the original SWE-bench."

In February 2026 the same company stopped reporting the benchmark. Its post "Why SWE-bench Verified no longer measures frontier coding capabilities" audited "138 SWE-bench Verified problems that OpenAI o3 did not consistently solve over 64 independent runs" and found that "59.4% of the 138 problems contained material issues in test design and/or problem description". On contamination: "all frontier models we tested were able to reproduce the original, human-written bug fix used as the ground-truth reference, known as the gold patch, or verbatim problem statement specifics for certain tasks". Its conclusion: "improvements on SWE-bench Verified no longer reflect meaningful improvements in models' real-world software development abilities. Instead, they increasingly reflect how much the model was exposed to the benchmark at training time." Two design lessons are stated in the post itself: "benchmarks sourced from publicly available material carry contamination risk", and "automated scoring is tricky to get right; perfect test cases should fully verify correct functionality, being both agnostic to specific unimportant implementation details and also robust to shortcut solutions."

For your own PR set the transfer is direct. Audit tasks that no run solves, because Anthropic's rule holds here too: "a 0% pass rate across many trials (i.e. 0% pass@100) is most often a signal of a broken task, not an incapable agent". Prefer PRs from private repositories over open-source history the model may have trained on. And write labels that accept any fix of the real problem, not only the one the original author wrote.

### What the M7 capstone measures

The capstone exercise runs on a small Go service with a TypeScript frontend, proto files, numbered migrations and a changelog, with 12 labelled PR patches containing planted issues. Its stages include a verify gate that runs the repository's tests on the patched tree, a blocker ranking from repository signals such as stale migration numbers and missing approvals, precision and recall of findings against labels using this module's harness, and traces with cost per PR. From this lesson it takes:

- per-severity precision and recall with a written matching rule, and blocker recall as the number that gates a change to the agent;
- the verify gate as a deterministic input the agent must report and may not contradict;
- cost per PR from the run's `total_cost_usd`, tracked in the score history from lesson 05;
- pass^k on the blocker verdict, since a reviewer that flags a blocker on some runs and not on others cannot be trusted on any one run (lesson 04);
- time-to-merge and reverts as lagging checks once the agent runs on real PRs, not as gates.

## Common pitfalls

- **One F1 for all findings.** Nits dominate the count and hide blocker recall. Report per severity and gate on blockers.
- **An unwritten matching rule.** Two people scoring the same output get different precision. Write down file, line window, duplicate and severity rules.
- **Labels copied from the original fix.** A different correct fix is scored wrong, the SWE-bench "narrow test" problem. Label the defect so any correct fix scores.
- **A PR set mined from public repositories.** The model may have seen the fix. Use private history where you can, and keep a planted set it cannot have seen.
- **Gating on time-to-merge.** It moves weeks later and with team load. Use it to validate the eval set, not to block a PR.
- **Letting the agent overrule the build.** A review that calls a PR safe while tests fail is wrong by construction. Feed gate results in and check the agent cites them.

## What interviewers ask

**How would you evaluate an AI code reviewer?**
Build a labelled set of PRs with known issues by severity, including clean PRs, and score findings with precision and recall per severity under a written matching rule, gating on blocker recall. Add deterministic verify gates on the patched tree and track cost per PR, with time-to-merge and revert rate as lagging checks.

**Where do labels for a review eval come from?**
From history: bug-fix commits traced back to the PR that introduced the bug, revert commits, review comments that led to changes, plus planted issues for rare categories. Double-label a sample and check agreement before relying on it.

**What went wrong with SWE-bench Verified?**
Its tasks came from public repositories, so frontier models had seen gold patches, and an audit of 138 tasks a strong model did not consistently solve found 59.4% with material flaws in tests or descriptions. Scores came to measure exposure and grader quirks more than coding ability, so OpenAI stopped reporting it.

**Why separate verify gates from the agent's findings?**
Build and test results are facts that are cheap to check and cannot hallucinate, while findings are judgments that need labels. Keeping them apart lets you grade the judgment without crediting the agent for what the test runner found.

**Which metric would you gate a new review-agent version on?**
Blocker recall on the labelled set with a floor on blocker precision, plus pass^k on the blocker verdict across repeated runs. Cost per PR as a ceiling, and time-to-merge only as a later confirmation.

## Sources

- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), Anthropic, published 2026-01-09, checked 2026-10-17
- [SWE-bench: Can Language Models Resolve Real-World GitHub Issues?](https://arxiv.org/abs/2310.06770), Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan, arXiv:2310.06770, published 2023-10-10, checked 2026-10-17
- [Introducing SWE-bench Verified](https://web.archive.org/web/20260101233457/https://openai.com/index/introducing-swe-bench-verified/), OpenAI, published 2024-08-13, checked 2026-10-17 (Internet Archive copy; openai.com answers automated link checks with HTTP 403)
- [Why SWE-bench Verified no longer measures frontier coding capabilities](https://web.archive.org/web/20261015182204/https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/), OpenAI, published 2026-02-23, checked 2026-10-17 (Internet Archive copy, same reason)
- [rjust/defects4j](https://github.com/rjust/defects4j), README, checked 2026-10-17
- [DORA's software delivery performance metrics](https://dora.dev/guides/dora-metrics/), checked 2026-10-17
- Course documents and code (repository files, not web sources): the lesson helpers in `course/m2-evals-lab/lesson_support/src/evals_lab_lessons/`
