# Reading a PR with a read-only agent

**Prerequisites:** [lesson 02](../02-conventions-of-a-go-ts-proto-migrations-repo/), which selects the rules that go into the reviewer's prompt.

## Why this matters for the factory

A pre-review agent reads code written by another agent, often from a branch nobody has looked at yet. That makes its input untrusted: the patch can contain anything, including text written to steer a model. The safest reviewer is one that cannot act on what it reads. It can open files, search and list, and nothing else: no shell, no edits, no network, no subagents it could hand work to. If you have run a review harness in an interactive session, you have relied on permission prompts for this. A gate runs unattended, so nobody is there to answer a prompt, and the restrictions have to hold by construction.

The second requirement is that the reviewer's answer is usable by code. Lesson 01 needs findings as records; a reviewer that sometimes answers in prose, sometimes in JSON with a misspelt field, breaks every stage after it. This lesson covers the options that make the agent read-only, the schema that makes its answer data, what goes into the prompt, what a review costs, and how a run can fail.

## Core idea

Stage 02 of the capstone runs one `claude_agent_sdk.query` per PR with options that remove every tool except three readers, keep those readers inside the patched tree, deny anything that would otherwise prompt, ignore the repository's own settings and MCP configuration, cap turns and spend, and require a structured answer. The working directory is a copy of the repository with the patch already applied, so when the agent reads `internal/api/handlers.go` it reads the version the PR would merge, and the line numbers it reports refer to that version.

The answer is checked twice. The SDK validates it against the JSON schema and re-prompts the model when it does not fit; the pipeline then validates each finding again with a Pydantic model and treats anything unexpected as a failed review. A failed review is retried once and then recorded as failed, and the run moves on to the next PR. The gate never invents a clean review because the model did not answer.

## Mechanics

### Options that make the agent read-only

The reviewer's options are `allowed_tools=[]`, `disallowed_tools=["Edit", "Write", "Bash", "WebFetch", "WebSearch", "Agent"]`, `permission_mode="dontAsk"`, a `PreToolUse` hook that guards the readers, `setting_sources=[]`, `strict_mcp_config=True`, `cwd` set to the patched tree, plus `max_turns`, `max_budget_usd` and `output_format`. Each option closes a different gap.

- **Bare names in `disallowed_tools` remove tools.** The permissions guide is precise: with `disallowed_tools=["Bash"]`, "The `Bash` tool definition is removed from the request. Claude does not see the tool and cannot attempt it", while a scoped rule like `Bash(rm *)` leaves Bash available and only denies matching calls (Configure permissions). A reviewer does not need a shell at all, so it does not get one.
- **`allowed_tools` approves, it does not restrict, so the reviewer passes none.** The reference says it "does not restrict Claude to only these tools" and that "Other unlisted tools fall through to `permission_mode`" (Agent SDK reference - Python). A bare entry such as `Read` approves every call to that tool, wherever the file is. File reads inside the working directory need no approval in the first place, so listing the readers would add exactly one thing: reads outside the tree, such as `~/.ssh` or `~/.aws/credentials`.
- **`dontAsk` turns prompts into denials.** In this mode "Any call that would otherwise prompt is denied" (Configure permissions), and the guide's recipe is the reviewer's: "For a locked-down agent, pair `allowedTools` with `permissionMode: "dontAsk"`". The same paragraph explains why `Agent` is on the deny list anyway: calls that need no approval still run, "such as read-only Bash commands, tools like `Agent` that don't ask before running, and file reads inside your working directories". A reviewer that can spawn a subagent can delegate to an agent with a different tool set, so its bare name goes into `disallowed_tools`.
- **A hook keeps the readers in the tree.** `review.read_guard(tree)` is a `PreToolUse` hook on `Read`, `Grep` and `Glob` that resolves `file_path`, `path` and a `Glob` pattern against the tree and denies anything that lands outside it: an absolute path, `~`, or `../`. Hooks come first in the permission evaluation order, before deny and allow rules (Configure permissions), so this holds even if a later change pre-approves the readers again. The tests call the hook with `/Users/x/.ssh/id_rsa` and a `../` path and expect a deny.
- **`setting_sources=[]` and `strict_mcp_config=True` keep the repository out of the configuration.** An empty list disables "user, project, and local settings", and strict MCP config means "use only the servers passed in `mcp_servers` and ignore project `.mcp.json`, user settings, plugin-provided MCP servers" (Agent SDK reference - Python). Without them, a PR that adds a permissive `.claude/settings.json` or an MCP server to the tree under review would configure its own reviewer.
- **Caps.** `max_turns=20` bounds the tool loop and `max_budget_usd=0.40` stops a review that runs away; M3 covered why the budget is an estimate that "can pass this value, so leave headroom".

The Agent SDK's subagent docs describe the same pattern for a nested reviewer: "A `doc-reviewer` subagent might only have access to Read and Grep tools, ensuring it can analyze but never accidentally modify your documentation files" (Subagents in the SDK). The capstone applies it to the top-level agent, where there is no parent to fall back on.

### The findings schema, enforced twice

`output_format={"type": "json_schema", "schema": FINDINGS_SCHEMA}` asks the SDK for validated JSON. The schema is flat on purpose: an object with a `summary` of at least 20 characters and a `findings` array whose items have `additionalProperties: false`, six required fields, enums for `severity` and `category`, `line` at least 1, `confidence` in [0, 1] and an optional `rule`. The structured-outputs guide explains how it is enforced: the SDK "validates the output against it, re-prompting on mismatch. If validation does not succeed within the retry limit, the result is an error instead of structured data", and "The SDK validates schemas with JSON Schema draft-07" (Get structured output from agents). Its advice matches the design: "Keep schemas focused. Deeply nested schemas with many required fields are harder to satisfy."

Two documented failure shapes matter. The error subtype `error_max_structured_output_retries` means "No valid output remained after multiple attempts", and "A result can also end with subtype `success` but no `structured_output` value ... Treat that case as a failure as well" (Get structured output from agents). Stage 02 raises `ReviewError` for both, for any other error result, for a `success` with `is_error`, for a stream that ends without a result and for SDK exceptions.

Then the pipeline validates each finding again with the shared `Finding` model, which enforces the same enums and bounds. That second check costs nothing and protects the stages after it from a schema that drifts from the model, or from a recorded answer that was never validated by the SDK at all, like the fake reviewer's YAML. The sample runs the lesson helper that does the same check on four invented findings, extracts changed files from a patch header that includes a deletion, and reads the per-PR cost of the course's live run.

Sample: `site/samples/m7/03-1.py`.

```python
from pathlib import Path

from capstone_lessons import accept_findings, changed_paths, live_summary

patch = """\
--- a/internal/api/routes.go
+++ b/internal/api/routes.go
@@ -10,3 +10,4 @@
--- a/web/src/legacy.ts
+++ /dev/null
@@ -1,2 +0,0 @@
"""
print("changed:", ", ".join(changed_paths(patch)))

keys = ("file", "line", "severity", "category", "message", "confidence")
rows = [
    ("internal/api/routes.go", 12, "major", "input-unvalidated", "limit reaches the store", 0.8),
    ("internal/api/routes.go", 0, "major", "input-unvalidated", "line zero cannot be cited", 0.7),
    ("web/src/legacy.ts", 1, "critical", "test-removed", "the only formatting test is gone", 0.9),
    ("internal/api/routes.go", 14, "minor", "naming", "the handler name says nothing", 0.5),
]
raw = [dict(zip(keys, row, strict=True)) for row in rows]
accepted, rejected = accept_findings(raw)
print(f"accepted {len(accepted)} of {len(raw)}")
for reason in rejected:
    print(" ", reason)

live = live_summary(Path("course/m7-capstone/fixtures/live_review_run.json"))
print(f"live run on {live['model']}: {live['reviewed']} of {live['prs']} PRs reviewed")
print(
    f"cost per reviewed PR, USD: min {live['usd_min']:.4f}"
    f"  median {live['usd_median']:.4f}  max {live['usd_max']:.4f}"
)
print(f"turns: median {live['turns_median']}  max {live['turns_max']}")
print(f"seconds per PR, tests and review: median {live['seconds_median']:.1f}")
```

Output, run on 2026-10-17:

```
changed: internal/api/routes.go, web/src/legacy.ts
accepted 1 of 4
  internal/api/routes.go:0 rejected on line
  web/src/legacy.ts:1 rejected on severity
  internal/api/routes.go:14 rejected on category
live run on claude-opus-5-5: 11 of 12 PRs reviewed
cost per reviewed PR, USD: min 0.0427  median 0.0664  max 0.0800
turns: median 3  max 5
seconds per PR, tests and review: median 11.6
```

Only one of the four findings survives. Line 0 cannot be cited, `critical` is not a severity of this schema and `naming` is not one of the twelve categories. With the SDK's validation on, such answers are re-prompted before they reach your code; the second check is what catches them when they come from anywhere else. Note the deleted file in the changed list: `changed_files` reads `--- a/` headers too, so a PR that deletes a test is still a PR that touches it, and findings on that file survive the touched-files filter.

### What goes into the prompt

The prompt is assembled from four parts: the PR's id, title and description from `meta.json`; the bodies of the rules that `rules.for_files` selects for the changed files, and no others; an instruction that only issues the patch introduces count and that `file` and `line` refer to the new version of the file; and the patch itself. The system prompt tells the agent that the working directory already holds the patched repository and that it may read but never change anything.

The instruction about introduced issues matters because models report pre-existing problems readily. Anthropic's managed reviewer gives them their own severity, Pre-existing, defined as "A bug that exists in the codebase but wasn't introduced by this PR" (Read and request reviews on a pull request). The capstone does not score them at all: stage 03 drops any finding on a file the patch does not touch, because the labels never name such a file. The best-practices page warns about the opposite failure too: "A reviewer prompted to find gaps will usually report some, even when the work is sound", so the reviewer should be told to "flag only gaps that affect correctness or the stated requirements" (Best practices for Claude Code). In this pipeline, the closed category list and the confidence threshold do that job.

### Cost and time per PR

The sample's second half reads `course/m7-capstone/fixtures/live_review_run.json`, the record of the stage 08 run on `claude-opus-5-5`. Eleven of twelve PRs were reviewed (the twelfth did not apply, so it was blocked without a review), each for between 0.0427 and 0.0800 USD, with a median of three turns and never more than five. No review came near the 0.40 USD cap or the 20-turn cap, and with no reader pre-approved the agent still read the files it needed inside the tree. The median PR took 11.6 seconds, and that figure includes applying the patch and running both test suites, not only the model.

Those numbers say something about the design. A reviewer with three readers and a focused prompt does little exploration: it reads the diff it was given, opens a file or two to check context, and answers. A broader tool set or a vaguer prompt would cost more per PR without being more likely to find a reused field number. The cap is still worth keeping, as the backstop for the PR that sends the agent searching the whole tree.

### How a review fails, and what the gate does then

- **No usable answer.** Schema retries exhausted, a `success` without structured output, an error result or an exception: `ReviewError`, retried once, then the PR is recorded as `review-failed` with its cost so far, and the report says so. The live run had no failed reviews.
- **Claims the reviewer cannot back.** A summary saying the tests pass while the verify gate failed. Stage 03 keeps the summary and attaches the gate's note, and lesson 01 explained why the gate wins.
- **Findings outside the patch, duplicates and low-confidence guesses.** Filtered before scoring; on the recorded reviewer that removes 10 of 26 findings.
- **Instructions in the input.** Text in a patch that tries to steer the reviewer can change its findings, and it can try to make the reviewer read a secret and quote it. The report is an output channel: `message` and `summary` land in `REPORT.md` and the run logs, and in a factory the report is posted back on the author's PR. The reviewer has no tool that writes or runs anything, and the read guard keeps its reads inside the patched tree, so what it can quote is the code under review. That is the reason the tool set is minimal and fenced, rather than relying on the model to ignore the text. The SDK's subagent docs show the platform taking the same view of model-to-model text: Claude Code "scans the final message for instruction-shaped patterns" before a parent reads a subagent's report (Subagents in the SDK).

## Pitfalls seen in the wild

- **`allowed_tools` as a whitelist.** It pre-approves; it does not hide the rest. Remove tools with bare names in `disallowed_tools` and deny the rest with `dontAsk`.
- **Pre-approving the readers.** A bare `Read` entry approves reads anywhere on the host. Reads in the working directory run without it; leave it out and fence the readers with a hook.
- **Forgetting `Agent`.** It does not ask before running, so `dontAsk` does not stop it. Deny it by name.
- **Loading the reviewed repository's settings.** A PR can add permissions or MCP servers to its own tree. Pass `setting_sources=[]` and strict MCP config.
- **Treating `success` as success.** Check for `structured_output`; a success without it is a failure.
- **Trusting the schema to be the only check.** Validate findings again in code; recorded and replayed answers never went through the SDK.
- **Reviewing the base tree.** Line numbers then refer to the old file and the agent cannot read what the PR adds. Review the patched copy.

## What interviewers ask

**How do you make a Claude Agent SDK reviewer read-only?**
Pre-approve nothing, remove `Edit`, `Write`, `Bash`, web tools and `Agent` by bare name so the model never sees them, set `permission_mode="dontAsk"` so anything that would prompt is denied, and add a `PreToolUse` hook that denies reads outside the working directory. Reads inside it need no approval, so the reviewer can still read the tree. Pass `setting_sources=[]` and strict MCP config so the repository under review cannot configure its own reviewer, and cap turns and budget.

**How do you get findings you can score instead of prose?**
`output_format` with a flat JSON schema: closed enums for severity and category, a positive integer line, confidence in [0, 1], no extra properties. The SDK validates and re-prompts; treat `error_max_structured_output_retries` and a success without `structured_output` as failures, and validate each finding again in code.

**What does a review like this cost, and what drives it?**
On the course's live run, between 4 and 8 cents per PR on Opus 5.5, a median of three turns, about 12 seconds per PR including the tests. The drivers are turns and context: a minimal tool set and a prompt that carries the diff and only the matching rules keep exploration short.

**A patch contains text telling the reviewer to approve it. What happens?**
The reviewer can be misled into reporting nothing, which is why it does not decide alone: deterministic blockers and the verify gate still apply, and the human sees the report. It cannot be misled into acting, because it has no tool that writes, runs commands, fetches URLs or spawns agents. It could be misled into reading a secret and quoting it in the report, which is an output channel back to the author, so its readers are not pre-approved and a hook denies any read outside the patched tree.

## Sources

- [Configure permissions](https://code.claude.com/docs/en/agent-sdk/permissions), Claude Agent SDK docs, checked 2026-10-17
- [Get structured output from agents](https://code.claude.com/docs/en/agent-sdk/structured-outputs), Claude Agent SDK docs, checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), `ClaudeAgentOptions`, checked 2026-10-17
- [Subagents in the SDK](https://code.claude.com/docs/en/agent-sdk/subagents), Claude Agent SDK docs, checked 2026-10-17
- [Read and request reviews on a pull request](https://code.claude.com/docs/en/code-review-pull-requests), section Severity levels, Claude Code docs, checked 2026-10-17
- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices), section Add an adversarial review step, checked 2026-10-17
- Course code and records (repository files, not web sources): stages 02, 03 and 08 in `course/m7-capstone/README.md`; the live record `course/m7-capstone/fixtures/live_review_run.json`; the lesson helpers in `course/m7-capstone/lesson_support/src/capstone_lessons/`
