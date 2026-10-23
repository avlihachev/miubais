---
title: "M7 Capstone: pre-review"
freshness: skip
---

The pre-review agent that scores PRs and ranks what blocks production: path-scoped rules, a read-only reviewer with structured findings, a verify gate, blockers from repository signals, metrics against labels, and the case for running it.

## Lessons

- [01 Review as a measurable pipeline](./01-review-as-a-measurable-pipeline/)
- [02 Conventions of a Go, TypeScript, proto and migrations repository](./02-conventions-of-a-go-ts-proto-migrations-repo/)
- [03 Reading a PR with a read-only agent](./03-reading-a-pr-with-a-read-only-agent/)
- [04 Blocker ranking from repository signals](./04-blocker-ranking-from-repository-signals/)
- [05 From pre-review to what blocks prod](./05-from-pre-review-to-what-blocks-prod/)
- [06 Interview angle](./06-interview-angle/)

## Exercise

[M7 capstone](/exercises/m7-capstone/): build `capstone`, a pre-review gate over the `go-ts-mini` fixture and its twelve pull requests, with tests and hints.

1. `01-rule-loader`: load `.claude/rules` with their `paths` frontmatter, match globs with `**`, `*`, `?` and braces, and select the rules for a PR's changed files.
2. `02-review-runner`: a read-only Agent SDK reviewer with a structured findings schema, a prompt built from the matched rules and the patch, and every failure raised as a review error.
3. `03-filter-and-dedupe`: drop findings on untouched files and below the confidence threshold, merge duplicates, and let the verify gate override a summary that claims the tests pass.
4. `04-verify-gate`: apply the patch to a copy and run `go test` and `node --test`, with no test run when the patch does not apply (needs Go and Node).
5. `05-blocker-ranking`: conflict, failed verify, stale migration, missing second approval and unreviewed age, weighted and ranked per PR.
6. `06-review-metrics`: match findings to labels by file, line window and category, one to one, and compute precision, recall and blocker recall.
7. `07-review-policy`: decide merge, hold or block for all twelve PRs and name the categories that block without a human (judgment stage; needs Go and Node).
8. `08-live-review`: review all twelve PRs with a real model and write the report with cost, verdicts and metrics (needs a Claude login, Go and Node).
