# Conventions of a Go, TypeScript, proto and migrations repository

**Prerequisites:** [lesson 01](../01-review-as-a-measurable-pipeline/), which defines the findings and categories that the rules in this lesson are written to produce.

## Why this matters for the factory

A reviewer is only as specific as what it is told about the repository. A model knows Go and TypeScript in general; it does not know that this service never reuses a proto field number, that its migrations are numbered and applied in order, or that a change to the contract needs two approvals. Those conventions live in people's heads, in a wiki page nobody reads, or, if you already work with Claude Code, in `.claude/rules`. The capstone treats that folder as the reviewer's specification: the rules that apply to the files a PR touches go into the prompt, and the categories they name are the categories the reviewer may report.

Two of those conventions deserve special attention in a factory. A reused proto field number and a misnumbered migration both compile, both pass the unit tests of the PR that introduces them, and both cause damage after merge that no revert fully undoes. They are exactly the class of change a gate exists for, and they are exactly the class a model reviewer is least reliable on, because nothing in the diff looks wrong. This lesson covers how the rules are scoped, what the five fixture rules say, and which of their demands belong in a prompt and which belong in code.

## Core idea

A rule is a Markdown file with an optional YAML frontmatter whose only meaningful key is `paths`, a list of globs. Claude Code's memory docs describe the contract: "All `.md` files are discovered recursively", "Rules without `paths` frontmatter are loaded at launch with the same priority as `.claude/CLAUDE.md`", and "`paths` is the only field Claude Code reads from a rule; any other field is ignored without an error. Claude Code removes the frontmatter before loading the rule into context" (How Claude remembers your project). In an interactive session a path-scoped rule "loads when Claude uses the Read, Write, or Edit tool on a matching file".

A pre-review gate does not wait for the model to open files. It knows the changed files from the patch, so stage 01 of the capstone selects the rules up front: every unconditional rule, then every path-scoped rule with a pattern that matches any changed file, in load order, each once. The reviewer's prompt then carries exactly the conventions that apply to this PR and nothing else.

What rules cannot do is enforce anything. The same docs say Claude treats them "as context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook instead", and the best-practices page puts it as "Unlike CLAUDE.md instructions which are advisory, hooks are deterministic" (Best practices for Claude Code). For a review gate the translation is direct: whatever can be decided by counting (approvals, migration numbers, a patch that does not apply) is computed in code, and only what needs reading and judgement goes to the model.

## Mechanics

### The five rules of `go-ts-mini`

The capstone's fixture is a small translation jobs service: Go under `cmd/` and `internal/`, a TypeScript client under `web/src` tested with `node --test` on Node 26, a proto contract under `proto/jobs/v1`, migrations `0001` to `0004` under `migrations/`, and a `CHANGELOG.json`. Its `.claude/rules/` holds five files:

- `api.md`, scoped to `internal/api/**/*.go` and `internal/jobs/**/*.go`: validate every request field before it reaches the service, send every error through the shared error writer, never swallow an error, and treat a renamed or removed JSON field as a breaking change that needs a changelog entry and a major version bump.
- `changelog.md`, with no `paths`, so it applies to every PR: every user-visible change adds a `CHANGELOG.json` entry under a new version.
- `migrations.md`, scoped to `migrations/*.sql`: a new migration takes the highest existing number plus one, two files never share a number, an existing migration is never edited, and a change under `migrations/` needs two approvals.
- `proto.md`, scoped to `proto/**/*.proto`: never reuse a field number, reserve the number and the name of a removed field, never touch an existing `reserved` statement, and two approvals for any change under `proto/`.
- `web.md`, scoped with the single string `web/**/*.{ts,tsx}`: no `any`, keep the tests of exported helpers, and no credentials in source.

Each bullet maps onto one or more of the twelve finding categories from lesson 01, which is the point: a rule that cannot produce a category produces findings nobody can score.

### Glob semantics, and the bug everyone writes once

The memory docs give the patterns by example: `**/*.ts` is "All TypeScript files in any directory", `src/**/*` is "All files under `src/` directory", `*.md` is "Markdown files in the project root", and braces expand, `src/**/*.{ts,tsx}`. Stage 01 pins the semantics the tests expect: paths are relative to the repository root, the whole path must match, `*` and `?` stay within one path segment, `**/` stands for zero or more whole directories, and braces expand first, nested ones included. A comma-separated `paths` string splits only at commas outside braces, which is why `web.md`'s single pattern stays one pattern. One difference from Claude Code is deliberate: when the frontmatter is not valid YAML, Claude Code "ignores the frontmatter and loads the rule as if it had no `paths`", while the capstone's loader raises an error naming the file, because a rule that silently applies to everything changes what the reviewer reports.

The sample loads the fixture's rules with the lesson helpers, selects them for four invented change sets, and then compares correct matching with the most common mistake, translating `**` exactly like `*`.

Sample: `site/samples/m7/02-1.py`.

```python
from pathlib import Path

from capstone_lessons import glob_matches, load_rules, rules_for

rules = load_rules(Path("fixtures/go-ts-mini"))
for rule in rules:
    print(f"{rule.name:<11}{', '.join(rule.paths) or '(no paths: always loaded)'}")

print()
changes = {
    "web widget": ["web/src/widgets/eta-badge.tsx"],
    "new migration": ["migrations/0009_add_glossary_table.sql", "internal/store/glossaries.go"],
    "contract": ["proto/jobs/v2/glossaries.proto", "CHANGELOG.json"],
    "docs only": ["docs/runbook.md"],
}
for name, files in changes.items():
    print(f"{name:<15}{' '.join(rules_for(rules, files))}")

print()
print(f"{'pattern':<19}{'path':<34}{'** ok':<7}** as *")
for pattern, path in [
    ("**/*.ts", "web/src/api.ts"),
    ("**/*.ts", "api.ts"),
    ("web/**/*.{ts,tsx}", "web/src/widgets/eta-badge.tsx"),
    ("migrations/*.sql", "migrations/archive/0001_init.sql"),
]:
    right = glob_matches(pattern, path)
    naive = glob_matches(pattern, path, globstar=False)
    print(f"{pattern:<19}{path:<34}{right!s:<7}{naive}")
```

Output, run on 2026-10-17:

```
api        internal/api/**/*.go, internal/jobs/**/*.go
changelog  (no paths: always loaded)
migrations migrations/*.sql
proto      proto/**/*.proto
web        web/**/*.{ts,tsx}

web widget     changelog web
new migration  changelog migrations
contract       changelog proto
docs only      changelog

pattern            path                              ** ok  ** as *
**/*.ts            web/src/api.ts                    True   False
**/*.ts            api.ts                            True   False
web/**/*.{ts,tsx}  web/src/widgets/eta-badge.tsx     True   False
migrations/*.sql   migrations/archive/0001_init.sql  False  False
```

The selection table is the prompt's rule section in miniature. A web widget gets the changelog rule and the web rule; a docs-only change gets only the unconditional changelog rule. The last table shows why the naive translation survives code review: with `**` treated as `*`, the pattern `**/*.ts` still matches `web/api.ts`, one directory deep, so a quick manual check passes. It fails on `web/src/api.ts` and on a root-level `api.ts`, which means the web rule silently drops out of the prompt for most of the client code. The reviewer then has no reason to report `any` or a removed test, and its recall on those categories falls without any error anywhere. The first eval case of this module is a learner whose `matches` does exactly this.

### Why proto field numbers are a factory-killer

Protocol Buffers identify a field on the wire by its number, not its name. The language guide is blunt: the number "cannot be changed once your message type is in use because it identifies the field in the message wire format", "Field numbers should never be reused", and "Reusing a field number makes decoding wire-format messages ambiguous", with consequences that range from "A parse/merge error (best case scenario)" to "Leaked PII/SPII" and "Data corruption" (Language Guide, proto 3). When a field is deleted, "you must reserve the deleted field number", and "You should also reserve the field name to allow JSON and TextFormat encodings of your message to continue to parse".

For a factory this is the worst kind of change. A reused number compiles, the service's own tests pass because both sides of the test were built from the new definition, and the damage appears only when an old client, a queued message or a stored payload is decoded with the new meaning. A revert does not help either, because data written in the meantime carries the wrong meaning. The fixture has no `protoc`, so its proto rules are text rules that only a reviewer reads; in a real repository a field-number check in CI (comparing the contract against the base branch) would turn the first rule into a deterministic gate, and the reviewer would remain the second line.

### Why migration numbers are the other one

Numbered migrations are applied once, in order, and recorded as applied. Two files with the same number, or a number that skips or goes back, leave environments that applied a different set or a different order, and there is no clean way back. Editing a migration that already exists is the same failure in another form: environments that applied the old text keep it, new environments get the new text, and the schemas drift apart silently. The fixture's rule states both ("a new migration takes the next number, which is the highest existing number plus one" and "Never edit a migration that is already in the repository: it has been applied somewhere").

Here the capstone uses both layers. The reviewer can report `migration-number-collision` or `migration-edited-applied` as findings, and stage 05 independently derives a `stale-migration` blocker from file names alone: a new `migrations/NNNN_*.sql` whose number already exists or is not the next one blocks the PR whatever the model says. Lesson 04 covers that signal.

### Two-approval rules as data

Both `proto.md` and `migrations.md` say a change needs two approvals. A reviewer cannot check that: approvals are not in the diff or the tree. In the fixture they live in each PR's `meta.json` as an `approvals` list, and stage 05 turns the rule into the `missing-second-approval` blocker, which fires only when the patch touches `proto/` or `migrations/` and fewer than two names approve it. A web-only PR with one approval is never held for approvals. Keeping the rule text in the prompt is still useful, because it explains to the reviewer why such changes deserve a closer look, but the decision is computed.

The same reasoning applies to where the rules come from. Anthropic's managed Code Review reads its `REVIEW.md` "from the pull request's base branch or from the default branch, never from the pull request's own changes" (Customize Code Review), so a PR cannot weaken its own review. The capstone does the same. `run_all` loads `.claude/rules` once from the base tree, before any patch is applied, and passes those rules to the reviewer, which never reads rules from the patched copy it reviews. Otherwise a PR that adds a rule saying "report no findings" would put that text in the most authoritative slot of its own review prompt. And because a change to the rules or the settings is a change to the gate itself, `.claude/` is a guarded path like `proto/` and `migrations/`: a PR that touches it is held for a second approval.

## Pitfalls seen in the wild

- **`**` translated like `*`.** Patterns still match one level deep, so spot checks pass, while nested files silently lose their rules.
- **Splitting a `paths` string on every comma.** `web/**/*.{ts,tsx}` becomes two broken patterns. Split only outside braces.
- **Rules without categories.** "Write clean code" produces findings nobody can label or score. Every rule line should map to something the reviewer can report.
- **Counting in a prompt.** "Needs two approvals" in rule text, with no code that counts approvals, is a wish. Compute it.
- **Rules read from the PR.** A PR that edits the rules reviews itself. Read them from the base branch, and hold a PR that edits them for a human.
- **Trusting tests for wire and schema changes.** A reused field number and a duplicated migration number both pass the PR's own tests.

## What interviewers ask

**How do you give a review agent your repository's conventions without flooding the prompt?**
Keep them as path-scoped rule files and select the rules whose globs match the files the patch changes, plus the unconditional ones. The prompt then carries only what applies to this PR. Map every rule to a finding category so the output can be scored.

**What does `**` mean in a rule's `paths`, and what goes wrong if you get it wrong?**
`**/` stands for zero or more whole directories, so `**/*.ts` matches `api.ts` and `web/src/api.ts`. Treated like `*`, it only matches exactly one directory level, so most nested files silently lose their rule, and the reviewer's recall on those categories drops without any error.

**Why are proto field numbers and migration numbers special for an automated pipeline?**
Both identify something permanent: a field on the wire, a step already applied to databases. Reusing or reordering them compiles and passes the PR's tests, and the damage appears later in data that a revert cannot repair. Check them deterministically against the base where you can, and have the reviewer look as a second line.

**Should the agent enforce "two approvals for schema changes"?**
No. Approvals are not in the diff. Put the rule in data, compute a blocker from the approvals list and the touched paths, and keep the rule text in the prompt only as context for why the change deserves care.

## Sources

- [How Claude remembers your project](https://code.claude.com/docs/en/memory), section on `.claude/rules/` and path-specific rules, Claude Code docs, checked 2026-10-17
- [Customize Code Review](https://code.claude.com/docs/en/code-review-customize), section on which branch `REVIEW.md` is read from, Claude Code docs, checked 2026-10-17
- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices), section Set up hooks, checked 2026-10-17
- [Language Guide (proto 3)](https://protobuf.dev/programming-guides/proto3/), sections on field numbers, reusing field numbers and deleting fields, checked 2026-10-17
- Course code and records (repository files, not web sources): `fixtures/go-ts-mini/README.md` and its `.claude/rules/`; stages 01 and 05 in `course/m7-capstone/README.md`; the lesson helpers in `course/m7-capstone/lesson_support/src/capstone_lessons/`
