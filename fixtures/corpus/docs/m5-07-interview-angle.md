# Interview angle: security and compliance for agents

**Prerequisites:** lessons 01 to 06 of [M5](../), which this page assumes you have read.

This page collects what lessons 01 to 06 prepare you to answer out loud. Each answer points back to the lesson that covers it in depth.

## What they ask

**1. What is the core security problem with a coding agent?**
Text an attacker controls enters the context through tickets, files, web pages and tool results, and the model cannot reliably tell instructions from data; OWASP's ASI01 says so in its first paragraph. With a shell, write access and tokens, a followed instruction becomes an action under your credentials. The design assumption is that some injections will land, so the environment and the harness, not the model, decide what an action can reach. Anthropic's containment post: "The deterministic boundary is what gets hit when everything probabilistic misses" ([lesson 01](../01-threat-model-for-agent-factories/)).

**2. How do you defend against indirect prompt injection?**
Mark, measure, restrict. Wrap every tool result in a provenance tag with source, path and hash, escaping `<` and `>` so the payload cannot close the tag. Score it with a detector. When a result looks like an injection, set a taint that makes a `PreToolUse` hook deny `Edit`, `MultiEdit`, `Write`, `Bash`, `NotebookEdit` and non-allowlisted MCP tools until the host approves with an id the host minted and the model never saw. Keep the path and command policy on underneath, because the taint is set after a result returns and a same-turn call can slip past it ([lesson 02](../02-indirect-injection-and-provenance/)).

**3. How good are model-layer defences?**
Claude Code's auto-mode classifier never sees tool results by design and a separate probe warns on suspicious ones; its full pipeline blocks 0.4% of real benign traffic (n=10,000) but misses 17% of real overeager actions (n=52) and 5.7% of synthetic exfiltration (n=1,000), and Anthropic says it is not a replacement for careful human review on high-stakes infrastructure. The course's heuristic detector catches 88 of 90 corpus attacks with no false positives, on a corpus it was tuned on, so that is an upper bound ([lesson 02](../02-indirect-injection-and-provenance/)).

**4. Show me the evidence that your defences held against a real model.**
The course's live run planted corpus payloads in a README, a source comment and the ticket body. On the attempt where the agent read them, one tool result set the taint; both denials, one `Edit` and one `Bash`, came from the taint, there was no `curl` attempt, nothing under `tests/` changed and the audit log passed all ten checklist items, for 0.11 USD in four turns. Say the limits too: the earlier attempt never read the plants, the tainted run could not fix the ticket, the approval path was not exercised live, and one run is a demonstration, not a rate ([lesson 02](../02-indirect-injection-and-provenance/)).

**5. Walk me through the Agent SDK permission order, and where the sandbox fits.**
Hooks, deny rules, ask rules, permission mode, allow rules, `canUseTool`. A hook deny applies even in `bypassPermissions`, bare-name denies remove the tool from the request, `dontAsk` denies anything that would prompt, and `allowed_tools` does not constrain `bypassPermissions`. Claude Code's Bash sandbox is OS-enforced (Seatbelt, bubblewrap) and off by default; it limits writes and routes network through an allowlist that starts empty, but reads cover most of the machine including `~/.ssh` unless denied, environment variables are inherited, and file tools, hooks and MCP servers run outside it ([lesson 03](../03-permissions-sandboxing-and-secrets/)).

**6. How do you keep secrets out of the agent?**
Keep them out of the process: start it without them and give it short-lived scoped tokens, because the Agent SDK's `env` merges on top of the inherited environment rather than replacing it. Build subprocess environments from an allowlist. Scrub tool output in a `PostToolUse` hook that finds secrets in nested JSON and base64 blobs, leaves ordinary text byte for byte, and fails closed. Scrub audit payloads too ([lesson 03](../03-permissions-sandboxing-and-secrets/)).

**7. What must a remote MCP server check, and what is token passthrough?**
A bearer token in the `Authorization` header only, never the query string; valid, unexpired and issued for this server as its audience; carrying the operation's scope. Missing or invalid tokens get 401 with `resource_metadata` and a `scope` hint; a valid token without the scope gets 403 `insufficient_scope` with the full required scope. Checking scopes without audience lets any token from the same authorization server in. Token passthrough, accepting a client's token without that check and forwarding it downstream, is explicitly forbidden by the MCP specification; the server uses its own token for downstream calls ([lesson 04](../04-remote-mcp-and-oauth/)).

**8. How do you red team an agent, and does the EU AI Act require any of this?**
A fixed offline set of known attacks with exact pass conditions (no canary, no executed side effect) runs on every change as the regression test; a generator such as promptfoo explores new attacks on a schedule, and confirmed findings join the fixed set ([lesson 05](../05-red-teaming-with-promptfoo/)). On the Act: a coding agent for your own code is not an Annex III high-risk use as written, so Article 12 logging is good practice rather than a duty for it; the Omnibus moved Annex III obligations to 2 December 2027; Article 50 transparency has applied since 2 August 2026 and matters where generated text reaches the public ([lesson 06](../06-eu-ai-act-for-engineers/)).

## System design prompt

"Design the security controls for a factory agent that reads tickets from untrusted users and can open PRs."

A short model outline:

- **Threat model first.** Untrusted inputs: ticket title and body, attachments, linked pages, the repository's own files, dependency READMEs, tool and MCP results. Assets: source code, CI secrets, the Git token, MCP tokens, the reviewers' attention. Map them to ASI01 (goal hijack), ASI02 (tool misuse), ASI03 (privilege), ASI05 (code execution), ASI09 (forged approvals), and place each on a layer.
- **Environment.** Run each ticket in a disposable container or VM with the repository checked out and nothing else. No cloud credentials in it. Network egress through a proxy with an allowlist (package mirror, Git host, the MCP servers), knowing every allowed domain is a capability. The Git token is short-lived, scoped to one repository, allowed to push branches but not to merge or change protection rules.
- **Harness.** `dontAsk` with tools removed by bare name where not needed (no `WebFetch` if tickets do not need it), `strict_mcp_config`, setting sources off so the repository cannot configure its own agent. A `PreToolUse` policy: writes only under `src/` (tests and CI config need a human), deny `curl`, `wget`, `nc`, pipes to shells and `git push` outside the harness's own step. Provenance wrapping and a detector on every tool result in `PostToolUse`; a taint that denies side effects and MCP writes until a human approves in the PR system, with a host-minted id. Turn and budget caps.
- **Tools and tokens.** MCP servers validate audience and scopes on every request; the agent's tokens carry read scopes, and write tools are hidden from it. Ticket-tracker access is read-only. The PR is opened by the harness from the diff, not by the agent with its own credentials.
- **Output.** Scrub secrets from tool output, PR descriptions and logs. Generated text that leaves the company (release notes, replies to the ticket author) goes through human review, which is also what Article 50(4)'s exception asks for.
- **Human gate.** The PR always needs review; the pre-review gate from M7 adds deterministic blockers and a read-only reviewer. The reviewer sees the taint events and denials for that run, so a forged "already approved" in the ticket is visible.
- **Evidence.** A hash-chained audit log per run with the head stored outside the sandbox; a fixed red-team set from past incidents and the injection corpus in CI; scheduled generated red teaming with a budget; metrics: taint rate, denials per run, tickets blocked by taint, time to approve.

Close with the trades: a strict taint stops legitimate fixes whenever a ticket quotes something suspicious, so measure how often a human has to approve; a detector tuned on your corpus overstates its recall; and no control here makes the model trustworthy; the controls limit what it can reach.

## Take-home shape

A good 2 to 4 hour take-home on this topic hands the candidate a small agent harness (a scripted model, a hook interface, a toy repository), a labelled set of 40 to 60 injection and benign strings, and a stub MCP server, and asks for three things:

1. **A provenance hook and a taint policy with tests.** Wrapping that escapes content and attributes, a detector with recall and false-positive targets measured on the set, and a `PreToolUse` deny for side-effect tools while tainted, cleared only by a host-minted id. Tests include a payload that tries to close the tag and a tool result that says "approved".
2. **Token checks on the MCP stub.** 401 for missing, query-string, expired and wrong-audience tokens with `resource_metadata`; 403 `insufficient_scope` with the right `scope`; tests for each.
3. **A one-page threat model.** The OWASP agentic entries mapped to the harness, the layer and control for each, and three residual risks the candidate would accept, with what they would monitor.

Grade on the edges (a same-turn tool call before the taint is set, a token with the right scopes for another server, a secret in a nested JSON string), on whether the taint can be cleared by anything in context, and on honesty about what the detector numbers mean. A submission whose taint clears when a tool result says "approved", or whose server accepts any token with the right scopes, fails regardless of polish.
