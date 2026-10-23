---
title: M5 Security and compliance
freshness: skip
---

The coding-agent harness hardened against prompt injection: a threat model on the OWASP agentic taxonomy, provenance tags and a taint that blocks side effects, permissions, sandboxing and secrets, a remote MCP server with audience-bound tokens, red teaming with a fixed attack set, and an audit log measured against the EU AI Act's logging and transparency articles.

## Lessons

- [01 A threat model for agent factories](./01-threat-model-for-agent-factories/)
- [02 Indirect injection and provenance](./02-indirect-injection-and-provenance/)
- [03 Permissions, sandboxing and secrets](./03-permissions-sandboxing-and-secrets/)
- [04 Remote MCP and OAuth](./04-remote-mcp-and-oauth/)
- [05 Red teaming with promptfoo](./05-red-teaming-with-promptfoo/)
- [06 The EU AI Act for engineers](./06-eu-ai-act-for-engineers/)
- [07 Interview angle](./07-interview-angle/)

## Exercise

[M5 injection lab](/exercises/m5-injection-lab/): build `injection_lab`, the security layer around the M1 harness, against a 140-item injection corpus, with tests and hints.

1. `01-corpus-and-detector`: load the corpus and score text with a heuristic detector that meets recall and false-positive bounds on it.
2. `02-provenance-and-taint`: wrap every tool result in an escaped provenance tag and keep a taint that denies side-effect tools until the host approves.
3. `03-secrets-and-env`: scrub secrets from tool output, nested and encoded ones included, and build subprocess environments from an allowlist.
4. `04-remote-mcp`: a Streamable HTTP MCP server with bearer tokens checked for audience, expiry and scope, and the 401 and 403 challenges.
5. `05-redteam-offline`: the corpus attacks as a fixed red-team set against a fake target, and a promptfoo configuration for the same target.
6. `06-audit-log`: an append-only, hash-chained audit log and a ten-item checklist derived from the AI Act.
7. `07-threat-model`: map ASI01 to ASI10 to this harness and name the control for each (judgment stage).
8. `08-live-injection`: run the hardened harness on a planted tinyshop ticket and prove the policy held (needs a Claude login).
9. `09-redteam-live`: run promptfoo against the fake target (needs Node and an Anthropic API key; the course did not run this stage).
