---
title: "Interview angle: pre-review and what blocks prod"
description: The questions an interviewer asks about AI code review as a measured pipeline, path-scoped rules, read-only reviewers, verify gates, blocker ranking and how to justify a pre-review gate, a system-design prompt for a factory that auto-merges agent PRs, and what a short take-home on this topic looks like.
module: m7
order: 6
freshness: skip
---

**Prerequisites:** lessons 01 to 05 of [M7](../), which this page assumes you have read.

This page collects what lessons 01 to 05 prepare you to answer out loud. Each answer points back to the lesson that covers it in depth.

## What they ask

**1. How do you know an AI code reviewer works?**
Make its output data and score it against labels. Each finding is a record with file, line, severity, a category from a closed list, message and confidence; each label is a known issue with a file, a line range, a category and a severity. A written matching rule pairs them: same file, same category, a line within three lines of the label's range, most confident finding first, one label to one finding. Then report precision, recall and, before anything else, blocker recall, because a reviewer that misses a leaked secret has failed however tidy its other remarks are. Clean PRs belong in the set too, so that silence is tested ([lesson 01](../01-review-as-a-measurable-pipeline/)).

**2. What do the public AI code-review benchmarks tell you?**
The range to expect and the trade, not a ranking to import. GitHub's ReviewBench (219 PRs from 187 repositories) reports grounded precision and recall against a fixed gold set with one model judge for every agent. Augment's vendor benchmark spreads tools from 20% to 68% precision, and puts itself first on labels it corrected. Kodus measured the trade directly: a high-recall configuration found 84 bugs instead of 72 and produced 328 false positives instead of 170, so they made it opt-in. Every benchmark defines a match differently, and none contains your repository's failure modes, so you build your own small labelled set ([lesson 01](../01-review-as-a-measurable-pipeline/)).

**3. How does a review agent learn your repository's conventions?**
From path-scoped rule files: Markdown with a `paths` list of globs in the frontmatter, discovered recursively under `.claude/rules`, unconditional when they have no `paths`. A gate knows the changed files from the patch, so it selects the unconditional rules plus every scoped rule with a pattern that matches a changed file, and puts only those into the prompt. `**/` means zero or more whole directories: treat it like `*` and `**/*.ts` stops matching `web/src/api.ts`, the rule silently leaves the prompt, and recall on its categories falls without any error. Read rules from the base branch, never from the PR, so a PR cannot edit its own review, and hold a PR that edits the rules for a second approval; the capstone does both ([lesson 02](../02-conventions-of-a-go-ts-proto-migrations-repo/)).

**4. Why are proto field numbers and migration numbers special in an automated pipeline?**
They identify something permanent. A proto field number identifies the field on the wire, and reusing one "makes decoding wire-format messages ambiguous", with consequences up to data corruption. A migration number fixes the order in which a step was applied to every database. Both kinds of mistake compile and pass the PR's own tests, and a revert does not repair data written in the meantime. Check them deterministically where you can (a numbering check from file names, a contract diff against the base), keep the reviewer as the second line, and require two approvals as computed data, not as a sentence in a prompt ([lesson 02](../02-conventions-of-a-go-ts-proto-migrations-repo/)).

**5. How do you make an Agent SDK reviewer read-only and its output reliable?**
An empty `allowed_tools`, because a bare `Read` entry approves reads anywhere on the host while reads inside the working directory need no approval; `disallowed_tools` with the bare names `Edit`, `Write`, `Bash`, `WebFetch`, `WebSearch` and `Agent`, which removes them from the request; `permission_mode="dontAsk"`, which turns any prompt into a denial; `setting_sources=[]` and strict MCP config so the repository under review cannot configure its reviewer; a turn and budget cap; the patched tree as `cwd`; and a `PreToolUse` hook that denies `Read`, `Grep` and `Glob` outside that tree. `Agent` needs denying by name because it does not ask before running. The hook matters because the report is an output channel: an injected patch that gets the reviewer to read `~/.aws/credentials` would have it quoted back on the author's PR. For output, a flat JSON schema in `output_format` that the SDK validates and re-prompts on, with `error_max_structured_output_retries` and a success without `structured_output` both treated as failures, and each finding validated again in code ([lesson 03](../03-reading-a-pr-with-a-read-only-agent/)).

**6. What should block a merge without asking a model?**
Facts the repository holds: the patch does not apply (and then no tests run on the unpatched copy), the tests fail on the patched tree, a new migration reuses or skips a number, a proto or migrations change lacks its second approval, an unapproved PR has been open more than 14 days. Weight them (conflict 100, verify failed 90, stale migration 80, missing approval 60, age 30), sum per PR and rank. Keep the model's findings out of the score so one confident false positive cannot reorder the queue, and use them in the verdict instead ([lesson 04](../04-blocker-ranking-from-repository-signals/)).

**7. What is the difference between hold and block?**
Block means the change is wrong and needs a new commit: a conflict, red tests, a misnumbered migration, a blocker-severity finding after hygiene. Hold means it may be fine and needs a person: a second approval, a look at a major finding, a decision on a stale PR, ideally minutes of work and no code change. Anthropic's managed Code Review never approves or blocks and its check run never fails; if you gate on its severity counts, a missing count is no verdict, not zero findings ([lesson 04](../04-blocker-ranking-from-repository-signals/)).

**8. How would you justify a pre-review gate to leadership, and what are its limits?**
In delivery terms: a human confirms a ranked report in minutes instead of reading every agent diff cold (lead time), and broken tests, misnumbered migrations and similar problems stop before merge (change fail rate). The course's live run on Opus 5.5 cost 0.70 USD for twelve PRs, 4 to 10 cents per reviewed PR, with a median of about 12 seconds per PR including the tests. State the limits first: precision 0.58 means four findings in ten were noise, blocker recall 0.80 means the model missed one blocker issue in five (in both committed runs), and it was measured on twelve planted PRs. A reviewer that never blocks is cheaper than one that blocks wrongly, so let facts block and the model hold. Launch report-only, then measure time to merge, reverts, overrides and finding acceptance ([lesson 05](../05-from-pre-review-to-what-blocks-prod/)).

## System design prompt

"Design a pre-review gate for a factory that auto-merges agent PRs: what blocks, what holds, what you measure."

A short model outline:

- **Place it before the human, not instead of one.** Every agent PR goes through the gate on open and on push; the gate posts one report with a verdict (merge, hold, block), the reasons, and the evidence. Auto-merge happens only on `merge` for paths that allow it; everything else waits for a person or goes back to the author.
- **Deterministic stage first.** Apply the patch to a clean copy of the base; on a conflict, stop and block. Run the build and tests on the patched copy with a timeout, treating a missing toolchain as no result rather than a failure. Compute repository signals: schema migration numbering, contract changes against the base (field numbers, reserved names), required approvals by path, PR age without review. Each signal is a blocker with a kind, a detail and a weight.
- **Model stage second, read-only.** Select the path-scoped rules for the changed files from the base branch (a PR that edits them needs a second approval), build a prompt with those rules and the patch, and run a reviewer with only read tools fenced to the patched tree, no shell, no network, no subagents, no repository settings, a turn and budget cap and a structured findings schema. Validate the output again in code; retry a failed review once, then record it as failed, never as clean.
- **Hygiene and reconciliation.** Drop findings on untouched files and below a confidence threshold, deduplicate by file, category and nearby line, and let the test result override any claim the reviewer makes about the tests.
- **Verdict policy.** Block on conflict, failed tests, stale migration or a blocker-severity finding in a category you have chosen to auto-block (leaked secrets, migration number collisions, field-number reuse); the capstone blocks on any blocker-severity finding, and in production you restrict that to chosen categories. Hold on missing approvals, stale PRs and major findings. Merge otherwise. Keep the ranking score to deterministic signals.
- **Measure in two loops.** Offline: a labelled PR set from your own history plus planted cases for rare categories, scored with a fixed matching rule, gating every change to prompt, rules or model on blocker recall and precision, with repeated runs for consistency. Online: time to merge, human time per PR, reverts and hotfixes within a week by verdict, overrides in both directions, finding acceptance, cost per PR, failed reviews. Start report-only and turn on blocking per category once its false-block rate is near zero.

Close with the trades: more recall from the model costs noise that people learn to ignore; a strict gate stalls the factory and a lax one ships the reused field number; and every model number above is an estimate until a month of your own PRs confirms it.

## Take-home shape

A good 2 to 4 hour take-home on this topic hands the candidate a small repository with a few conventions (a numbered migrations folder, a contract file, a rules folder with path globs), a dozen PR patches with metadata, a recorded reviewer's findings for each, and labels for half the PRs, and asks for three things:

1. **Rules and signals with tests.** A rule loader with glob matching (`**`, `*`, braces) and rule selection per PR, and deterministic blockers (patch applies, migration numbering, approvals by path), each tested on edge cases: a root-level file under `**/*.ts`, a migration that skips a number, a web-only PR with one approval.
2. **Metrics with a written matching rule.** Hygiene for the recorded findings and precision, recall and blocker recall against the labels, with the matching rule stated in the README and tested: the line window, category equality, one to one.
3. **A one-page policy.** For the unlabelled PRs, a verdict and a reason each, which categories block without a human and why, and what the candidate would measure in the first month after launch.

Grade on the edges (a duplicate finding, a finding on an untouched file, a reviewer summary that contradicts the tests), on a matching rule that cannot be gamed by matching on file alone, on blockers that do not depend on the model, and on a policy that states its limits. A submission whose glob treats `**` like `*`, or that lets the reviewer's claim about tests stand against the test result, fails regardless of polish.
