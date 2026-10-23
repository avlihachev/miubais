# Interview angle: enforced harness

**Prerequisites:** lessons 01 to 06 of [M1](../), which this page assumes you have read.

## What they ask

**1. Why are hooks better than prompt instructions for a rule like "never edit tests"?**
An instruction is context the model weighs against everything else it reads, so a file or a tool result can talk it out of it. A `PreToolUse` hook runs in your process before the tool does and denies whatever the model believes; keep the instruction anyway, because a denied attempt costs a turn.

**2. Three hooks disagree about one call. What happens?**
They run in parallel and the most restrictive decision wins: `deny` over `defer` over `ask` over `allow`. An `allow` from every hook still does not override a deny or ask rule, so hooks can tighten the policy but never loosen it past the rules.

**3. When does `can_use_tool` fire, and why not rely on it for policy?**
Only when the permission flow falls through to a prompt: no hook, rule or mode decided first, and never in `dontAsk`. It fits interactive approval; a rule that must see every call belongs in a hook.

**4. How do you set permissions for an unattended agent?**
Run `dontAsk` with an explicit allow list, bare-name `disallowed_tools` for tools that must not exist, and `setting_sources=[]` so no settings file adds rules you did not write. `allowed_tools` alone only pre-approves, and `bypassPermissions` approves everything else.

**5. Why is the reviewer subagent read-only?**
It starts from a fresh context with only the diff, so it is not anchored on the coder's reasoning, and a reviewer that can edit stops being a check. Bind its verdict to a schema with `output_format`, then validate it in your own code before gating anything.

**6. How does a run survive a restart, and what does a stale resume look like?**
Store the `session_id` per ticket and pass it as `resume`; the id must be a valid UUID, and a stale one fails before any assistant output. Fall back to one fresh session, record that you did, and keep files in a worktree per ticket because a session restores only the conversation.

**7. Why can a run cost more than `max_budget_usd`, and how do you make a side effect safe to repeat?**
The budget is a client-side estimate checked after each response, so the response that crosses it still completes, and a resumed session carries its earlier cost. Leave headroom, and give every effect a stable key claimed by an atomic insert before it runs, so a repeat reads the stored result and a crash after the claim is surfaced rather than retried.

**8. How would you classify failures of an unattended coding agent, and what do you measure?**
By what the trace shows: loops, scope creep, skipped verification, retrying around a denial, following instructions found in tool output, budget blowouts, lost context. Per ticket measure turns, cost, denials, files changed and the harness's own test result, and report the stop-reason distribution and cost per shipped ticket, not a failure rate.

## System design prompt

"An agent takes tickets from a widget and ships PRs. What must the harness enforce, what do you measure, and when do you stop it?"

A short model outline:

- **Enforce in code.** A guard in `PreToolUse` that denies writes outside `src/`, resolves paths before comparing, blocks destructive and network commands, and fails closed when the hook itself errors. Run it in `dontAsk` with `setting_sources=[]`, in a per-ticket worktree, with the widget's ticket text treated as untrusted input.
- **Make effects safe to repeat.** Opening the PR, commenting and labelling go through idempotent tools keyed by ticket and operation, and sessions are stored per ticket with a fresh-session fallback.
- **Verify outside the agent.** The harness runs the acceptance tests after the agent stops and a read-only reviewer subagent checks the diff against a schema; neither a `success` subtype nor the agent's own summary counts as proof.
- **Measure.** Stop-reason distribution, turns and cost per ticket (median and 90th percentile, with the subagent split), denials per run, files outside scope, tests run or not, and cost per merged PR.
- **Stop it.** `max_turns` and `max_budget_usd` set from the 90th percentile of successful runs plus margin, a wall-clock deadline, and a `Stop` hook that refuses to finish before verification. At fleet level, pause intake when the `max_turns` share or the denial rate climbs, and sample those traces before touching a cap.

Close with the trade you are making: every deny can block a legitimate fix, every cap funds fewer long tickets, and you would review the denied and capped runs weekly to tune both.

## Take-home shape

A 2 to 4 hour take-home on this topic might give you a small repo with a few planted bugs and tickets, and ask for three things:

1. **A guard with tests.** A policy engine wired as a hook that handles `..`, symlinks, redirects in shell commands and an unknown tool, with a test for each and a deny when the guard itself raises.
2. **A run summary over a handful of tickets.** A table with turns, cost, stop reason and the harness's own test result per ticket, where a run that overshot its budget or hit its turn limit is never reported as success.
3. **A failure classification write-up.** A short document that sorts a set of recorded traces into categories with the tell for each, names the fix per category, and says which cap or check you would change first and why.
