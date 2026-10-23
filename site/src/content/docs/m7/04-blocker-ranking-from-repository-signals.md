---
title: Blocker ranking from repository signals
description: The signals that decide whether a PR can merge without asking a model, from a patch that does not apply to an unreviewed PR that has gone stale, their weights and the ranking a team lead reads, the difference between hold and block, and how this compares with gating on a managed reviewer's severity counts.
module: m7
order: 4
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/code-review-pull-requests
    title: Read and request reviews on a pull request
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/code-review
    title: Code Review
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/best-practices
    title: Best practices for Claude Code
    checked: 2026-10-17
  - url: https://git-scm.com/docs/git-apply
    title: git-apply
    checked: 2026-10-17
---

**Prerequisites:** [lesson 02](../02-conventions-of-a-go-ts-proto-migrations-repo/), which moves the approval and numbering rules out of the prompt and into data; this lesson computes them.

## Why this matters for the factory

Whether a patch applies, whether the tests pass on the patched tree, whether a new migration takes the right number, whether a contract change has its second approval, whether a PR has sat unreviewed for weeks: each of these is a fact the repository already holds. Computing them costs milliseconds or a test run, never varies between runs, and cannot be talked out of its answer by text in the patch.

These signals are also what a team lead needs first. Before anyone reads a finding, the useful question is "which of today's PRs can I merge, which need something from someone, and which are broken", in that order of urgency. A ranking built from repository signals answers it the same way every time, and the model's findings refine it rather than drive it. If your current review harness posts comments but never says which PRs are stuck and why, this is the missing half.

## Core idea

Stage 05 of the capstone turns five repository signals into blockers, each with a kind, a detail for the human and a weight:

| kind | weight | fires when |
| --- | ---: | --- |
| `conflict` | 100 | the patch does not apply to the base |
| `verify-failed` | 90 | `go test` or `node --test` fails on the patched tree |
| `stale-migration` | 80 | a new migration reuses a number or is not the next one |
| `missing-second-approval` | 60 | the patch touches `proto/`, `migrations/` or `.claude/` with fewer than two approvals |
| `unreviewed-age` | 30 | no approvals and created more than 14 days before the as-of date |

A PR's score is the sum of its blockers' weights, and the ranking sorts PRs by score, highest first, then by id. Separately, stage 08 gives each PR a verdict from its blockers and its cleaned findings: `block` for a blocker-severity finding or a `conflict`, `stale-migration` or `verify-failed` blocker; otherwise `hold` for a major finding, a `missing-second-approval` or `unreviewed-age` blocker, or a review that failed; otherwise `merge`. Each verdict carries its reason, the blocker or the finding that produced it, so the report can say `block: blocker finding secret-in-code at web/src/client.ts:12` for a PR whose blocker score is 0.

The score orders attention. The verdict decides what may happen to the PR. They are deliberately not the same thing, and the sample shows a PR where they disagree.

## Mechanics

### Signals that need no model

**Conflict.** Stage 04 copies the base tree and runs `git apply --check` and then `git apply` with the patch inside the copy. The `--check` flag makes git "see if the patch is applicable to the current working tree and/or the index file and detects errors" without applying anything (git-apply). A refusal yields `Applied(ok=False)` with the conflicting files parsed from git's error lines, and the gate then runs no tests: running them on the unpatched copy would report a pass for code that is not in the PR. A conflict is the heaviest blocker because nothing else about the PR can be trusted until it is rebased.

**Verify failed.** When the patch applies, stage 04 runs `go test ./...` and `node --test` on the copy. Either side failing produces `verify-failed`, with a detail naming the side. A tool that is missing is `None`, not a failure: a gate must not block every PR because the runner lacks Node.

**Stale migration.** Stage 05 reads the base tree's `migrations/` and the patch's changed files. Every added `migrations/NNNN_*.sql` that does not exist in the base must take the next free number in order: the first new one `max existing + 1`, the next `+ 2`. Reusing an existing number or skipping one is `stale-migration`. Editing an existing migration is not this blocker; it is a finding (`migration-edited-applied`) for the reviewer, because only reading the change shows whether it is harmless.

**Missing second approval.** The rule from lesson 02 as code: any changed path under `proto/` or `migrations/` and fewer than two names in `meta.json`'s `approvals`. The capstone adds `.claude/`, because a PR that edits the review rules or settings changes the gate itself. A PR that touches none of them is never held for approvals, however few it has. Renames count on both sides: a PR that moves a file out of `migrations/` touches `migrations/`.

**Unreviewed age.** No approvals at all and `created_at` more than 14 days before the run's as-of date. Fourteen days exactly is not enough. This is the only signal about the process rather than the change: an old, unreviewed PR has a base that has moved.

### Weights and the ranking

The weights encode one policy: things that are wrong with the change outrank things that are missing around it, and among the wrong ones, the cheaper a fix is to confirm, the higher the PR sits. A conflict needs a rebase before anything else is meaningful. A failing test is a fact about the code. A misnumbered migration is a fact about the order of the schema. An approval and an old PR are about people. Summing them lets a PR with two problems outrank a PR with one, which is what a lead scanning the list wants.

The sample ranks seven invented PRs with the lesson helpers, which implement the same signals, weights and verdict rule on a plain record of signals instead of a patched tree.

Sample: `site/samples/m7/04-1.py`.

```python
from capstone_lessons import WEIGHTS, Signals, rank_prs

existing = (1, 2, 3, 4, 5, 6)
prs = [
    Signals("a-docs", touches=("docs/runbook.md",), approvals=1, age_days=2),
    Signals(
        "b-schema",
        touches=("migrations/0007_glossaries.sql",),
        approvals=1,
        age_days=1,
        existing_migrations=existing,
        new_migrations=(7,),
    ),
    Signals(
        "c-dup-migration",
        touches=("migrations/0006_due_at.sql",),
        approvals=2,
        age_days=3,
        existing_migrations=existing,
        new_migrations=(6,),
    ),
    Signals(
        "d-red-tests",
        touches=("internal/api/routes.go",),
        approvals=1,
        age_days=1,
        tests_failed=True,
    ),
    Signals("e-stale", touches=("internal/store/cache.go",), approvals=0, age_days=21),
    Signals(
        "f-rebase",
        touches=("proto/glossaries/v1/glossaries.proto",),
        approvals=1,
        age_days=5,
        applied=False,
    ),
    Signals(
        "g-ui-major",
        touches=("web/src/cart.ts",),
        approvals=1,
        age_days=1,
        finding_severities=("major", "minor"),
    ),
]

print("weights:", ", ".join(f"{kind} {weight}" for kind, weight in WEIGHTS.items()))
print(f"{'pr':<17}{'score':>5}  {'verdict':<8}blockers")
for row in rank_prs(prs):
    print(f"{row.pr:<17}{row.score:>5}  {row.verdict:<8}{', '.join(row.kinds) or 'none'}")
```

Output, run on 2026-10-23:

```
weights: conflict 100, verify-failed 90, stale-migration 80, missing-second-approval 60, unreviewed-age 30
pr               score  verdict blockers
f-rebase           160  block   conflict, missing-second-approval
d-red-tests         90  block   verify-failed
c-dup-migration     80  block   stale-migration
b-schema            60  hold    missing-second-approval
e-stale             30  hold    unreviewed-age
a-docs               0  merge   none
g-ui-major           0  hold    none
```

`g-ui-major` has no blocker at all, score 0, and is still `hold`: the reviewer reported a major finding, and the verdict uses findings while the score does not. The score ranks what repository signals say, which never varies between runs; the verdict combines them with the model's opinion, which can. Mixing a finding's severity into the score would let one confident false positive push a clean PR to the top of the list.

`f-rebase` shows why the score sums: it conflicts and touches `proto/` with one approval, so it ranks above a PR with failing tests. `b-schema` is a correct migration with one approval, which is `hold`, not `block`: nothing is wrong with the change, someone just has to approve it. `c-dup-migration` has its two approvals and still blocks, because a reused migration number is a fact about the change that no number of approvals fixes.

### Hold versus block

The distinction is about who acts and how long it takes. `block` means the change itself is wrong and goes back to the author (or the agent that wrote it): a conflict, a red test, a migration number collision, a blocker-severity finding such as a hard-coded secret. `hold` means the change may be fine and is waiting on a person: a second approval, a look at a major finding, a decision about an old PR. A hold should be resolvable by a human in minutes, without a new commit. A block needs a new commit.

A factory that blocks everything uncertain stalls; one that merges everything not provably broken ships the reused field number. With two states between merge and refuse, the certain problems stop the PR automatically and the uncertain ones go to a person with the reason already written down.

### Comparison: gating on a managed reviewer

Anthropic's managed Code Review takes the opposite default. "A review never approves or blocks the pull request, so the decision to merge stays with your team" (Code Review), and its check run "never concludes as a failure". It does give you a hook to gate on: the check run's details end in a machine-readable line with "a count per severity", for example `{"nit": 1, "normal": 2, "pre_existing": 0}`, and the docs suggest "fail the job if you want to gate the merge" when `normal`, the count of Important findings, is above zero. They add that when the line is missing, you should "treat it as no verdict rather than as zero findings" (Read and request reviews on a pull request).

The capstone's design agrees with both halves. A model's findings alone do not block in the managed service; in the capstone they can, but only at blocker severity, and only after hygiene. Repository signals block on their own because they are deterministic, the property the best-practices page asks for when it says "Unlike CLAUDE.md instructions which are advisory, hooks are deterministic". And a review that failed is recorded as failed, never as clean: the PR is held at least, with `hold: review failed` as its reason.

## Common pitfalls

- **Running tests on the unpatched tree after a failed apply.** The gate reports a pass for code the PR does not contain. Stop at the conflict.
- **Counting a missing toolchain as a failure.** Every PR blocks the day the runner image changes. `None` is not `False`.
- **Folding finding severity into the score.** One confident false positive outranks a real conflict. Keep the score to signals and let the verdict combine.
- **Approval rules that ignore paths.** Holding every one-approval PR trains people to rubber-stamp. Hold only the paths the rule names.
- **Off-by-one on age.** "More than 14 days" and "14 days or more" differ on exactly the PRs people argue about. Write the boundary down and test it.
- **Treating a missing review as zero findings.** A failed or skipped review is no verdict. Report it as such, and never let it become a merge.

## What interviewers ask

**Which merge blockers would you compute without a model?**
Patch applies, tests pass on the patched tree, schema migration numbering, required approvals for sensitive paths, and staleness of unreviewed PRs. They are cheap, deterministic, and cannot be argued with by text in the patch, so they should decide before any model finding does.

**How do you rank a queue of PRs for a reviewer?**
Weight each blocker by how fundamental it is (conflict above failing tests above schema order above approvals above age), sum per PR, sort by score then id. Keep the model's findings out of the score so a false positive cannot reorder the queue; use them in the verdict instead.

**What is the difference between hold and block?**
Block means the change is wrong and needs a new commit: conflict, red tests, a misnumbered migration, a blocker-severity finding. Hold means it may be fine but needs a person: an approval, a look at a major finding, a decision on a stale PR. A hold should take a human minutes and no code change.

**Would you gate merges on a managed AI reviewer's severity counts?**
Possibly as one input, on the important-severity count, and only with missing output treated as no verdict. Not as the only gate: the managed reviewer reads the diff and does not run anything, and it is designed never to block. Deterministic signals should gate first.

## Sources

- [Read and request reviews on a pull request](https://code.claude.com/docs/en/code-review-pull-requests), section Check run output, Claude Code docs, checked 2026-10-17
- [Code Review](https://code.claude.com/docs/en/code-review), Claude Code docs, checked 2026-10-17
- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices), section Set up hooks, checked 2026-10-17
- [git-apply](https://git-scm.com/docs/git-apply), Git documentation, option `--check`, checked 2026-10-17
- Course code and records (repository files, not web sources): stages 04, 05 and 08 in `course/m7-capstone/README.md`; the lesson helpers in `course/m7-capstone/lesson_support/src/capstone_lessons/`
