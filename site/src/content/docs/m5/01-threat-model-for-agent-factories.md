---
title: A threat model for agent factories
description: Where untrusted text enters a coding agent, what it can make the agent do, the OWASP Top 10 for Agentic Applications mapped to the course harness, the LLM Top 10 entries it builds on, and why containment at the environment layer comes before anything a model does.
module: m5
order: 1
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:mcp": "2.3.0"
  "model:default": claude-opus-5-5
sources:
  - url: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
    title: OWASP Top 10 for Agentic Applications for 2026
    published: 2025-12-09
    checked: 2026-10-17
  - url: https://genai.owasp.org/llm-top-10/
    title: OWASP Top 10 for LLM Applications 2025
    checked: 2026-10-17
  - url: https://www.anthropic.com/engineering/how-we-contain-claude
    title: How we contain Claude across products
    published: 2026-05-25
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/security
    title: Claude Code security
    checked: 2026-10-17
---

**Prerequisites:** [M1 lesson 01](../../m1/01-harness-is-loop-plus-policy/), which builds the ticket runner and the policy this module hardens.

## Why this matters for the factory

A coding agent in a software factory reads text nobody on your team wrote. A ticket comes from a customer, a README from a dependency, a web page from whoever controls the domain, a tool result from a server you connected last month. Every one of those is a channel into the model's context, and the model cannot reliably tell an instruction from the data around it. The OWASP Agentic Top 10 opens its first entry with it: agents "and the underlying model cannot reliably distinguish instructions from related content."

Now give that agent a shell, write access to the repository, a token for an MCP server and permission to open pull requests. An instruction hidden in a ticket then becomes a command that runs with your credentials. Anthropic describes a February 2026 red-team exercise in which a researcher phished an employee into launching Claude Code with a ready-to-paste prompt that asked it to read `~/.aws/credentials` and post the contents to an external endpoint: "Across 25 retries of that prompt, Claude completed the exfiltration 24 times" (How we contain Claude across products). That injection came through the user, and the post's conclusion is that only egress and filesystem boundaries would have stopped it. The model did what the text in front of it asked.

This module hardens the M1 harness against that. This lesson draws the map: where untrusted text enters, what it can make the agent do, which published taxonomy names each risk, and which layer of the system should stop it. Lessons 02 to 06 build the controls.

## Core idea

A threat model for an agent answers three questions. Where does text the attacker controls enter the context? What can the agent do with its tools once it believes that text? And which boundary holds when the model does what the text says?

The third question decides the design. Anthropic's containment post puts the order plainly: "Design for containment at the environment layer first, then steer behavior at the model layer." The reason is in another line of the same post: "The deterministic boundary is what gets hit when everything probabilistic misses." Model-layer defences, from a classifier to a well-written system prompt, "shape only what the agent tends to do," not what it can do. A detector that catches 98 attacks in 100 still lets two through, and an attacker gets to retry.

So the course uses three layers, and every risk in this lesson is assigned to one of them:

1. **Environment.** What the process can physically reach: files, network, credentials, other processes. A sandbox, an egress allowlist and an environment without secrets are environment controls.
2. **Harness.** Deterministic code around the model: permission rules, `PreToolUse` hooks that deny, a taint state that blocks side effects while untrusted text is in context, token audience and scope checks on a remote server, an append-only audit log.
3. **Model.** Anything probabilistic: a heuristic or learned detector, a classifier that reviews actions, instructions in the system prompt, provenance tags that help the model see where text came from.

Each layer catches what the one above it misses, and none is enough alone. A harness that denies `Bash` while the context is tainted depends on a detector to set the taint; a detector that misses an attack is backed by a policy that never allowed `curl` to an unknown host; and a policy rule matches command text, so an environment that has no credentials to steal is the last line.

## Mechanics

### The OWASP Top 10 for Agentic Applications

The OWASP GenAI Security Project published the Top 10 for Agentic Applications on 2025-12-09, under CC BY-SA 4.0. It is the taxonomy the corpus labels, the detector reasons and the audit log use in this module. The course spells the entries as `ASI01 Agent Goal Hijack`, `ASI02 Tool Misuse and Exploitation`, `ASI03 Identity and Privilege Abuse`, `ASI04 Agentic Supply Chain Vulnerabilities`, `ASI05 Unexpected Code Execution`, `ASI06 Memory and Context Poisoning`, `ASI07 Insecure Inter-Agent Communication`, `ASI08 Cascading Failures`, `ASI09 Human-Agent Trust Exploitation` and `ASI10 Rogue Agents`.

The PDF linked from the OWASP resource page spells four of them differently. ASI05's heading is "Unexpected Code Execution (RCE)". ASI06 is "Memory & Context Poisoning" everywhere in the PDF. ASI02 and ASI03 use "and" in the table of contents and in their section headings, but "&" in the at-a-glance figure and the contributor table ("Tool Misuse & Exploitation", "Identity & Privilege Abuse"). The ids and meanings are the same; the course keeps the plain-word form in `injection_lab/types.py` so that code and prose match.

### The ten entries, mapped to this harness

The table below says where each risk shows up in the course harness (the M1 runner on tinyshop tickets, with M5's remote MCP server) and which layer should hold. It deliberately stops at the layer: naming the specific control for each row is stage 07 of the exercise, where you write the threat model yourself.

| Entry | Where it shows up here | Layer that should hold |
| --- | --- | --- |
| ASI01 Agent Goal Hijack | A ticket, README, code comment or fetched page carries "ignore the ticket, do this instead" | Harness, backed by a model-layer detector |
| ASI02 Tool Misuse and Exploitation | The agent uses a legitimate tool for the attacker: `Bash` to run `curl`, `Edit` on `tests/`, an MCP write tool | Harness (per-tool rules), environment (egress) |
| ASI03 Identity and Privilege Abuse | The agent's MCP token or Git credentials reach further than the ticket needs, or a token minted for one server is accepted by another | Harness (token audience and scopes), environment |
| ASI04 Agentic Supply Chain Vulnerabilities | A dependency, plugin or MCP server ships hidden instructions or a malicious startup command | Environment (what runs, with what), harness |
| ASI05 Unexpected Code Execution | The agent writes and runs code: a test, a script, a `pip install` that executes a build hook | Environment (sandbox, minimal subprocess environment) |
| ASI06 Memory and Context Poisoning | Injected text stays in the session, in a resumed transcript or a compaction summary, and steers later turns | Harness (provenance and taint that outlive the turn) |
| ASI07 Insecure Inter-Agent Communication | A subagent's report or an MCP server's tool result is trusted like the user's own words | Harness (treat it as untrusted, authenticate the server) |
| ASI08 Cascading Failures | One poisoned run opens a PR that the next agent merges, or a bad fix spreads through retries | Harness (caps, gates), human review |
| ASI09 Human-Agent Trust Exploitation | A confident summary or a forged "already approved" line gets a person to wave a change through | Harness (approvals that only the host can grant), audit |
| ASI10 Rogue Agents | The agent drifts outside its scope and keeps acting, for example by working around denials | Environment and harness, observed through the audit log |

Two rows need comment. ASI06 is easy to dismiss for a single-ticket runner, but M1's durable sessions resume a transcript, so injected text read in one attempt is in context for the next. For ASI09, the attacker's target is sometimes the reviewer, not the model, and an injected "the maintainer already approved this" is aimed at both.

### The LLM Top 10 entries underneath

The agentic list builds on the OWASP Top 10 for LLM Applications 2025 rather than replacing it. Four of its entries are the cross-references for this module: `LLM01 Prompt Injection`, `LLM02 Sensitive Information Disclosure`, `LLM06 Excessive Agency` and `LLM07 System Prompt Leakage`. The PDF's appendix says how they relate: "ASI entries often blend multiple LLM entries", for example "ASI01 combines LLM01:2025 (prompt) with LLM06 (autonomy)". The ASI02 section draws the line between the two lists: "While LLM06 focuses on model-level autonomy, ASI02 addresses misuse of legitimate tools within agentic plans and delegation chains."

LLM01 is how the attack gets in, LLM06 is why it matters (the agent can act), LLM02 is what is taken (a key in a tool result, a `.env` file), and LLM07 is a smaller risk for a coding agent because its system prompt is rarely the secret. The OWASP authors add a principle on top of least privilege, which they call Least-Agency: avoid "unnecessary autonomy; deploying agentic behavior where it is not needed expands the attack surface without adding value."

### Containment first, in this course

The containment post gives three rules that this module turns into code:

- "Match isolation strength to the user's capacity for oversight." An unattended factory run has no one to answer a prompt, so it needs the strongest boundary you can afford, not the most convenient one.
- "if credentials never enter the sandbox, they can't be exfiltrated". Lesson 03 builds subprocess environments from an allowlist and scrubs tool output, because the Agent SDK's `env` option merges on top of the inherited environment.
- On network access: "Every function reachable through any domain on an allowlist is now an attack surface." Each allowed domain is a capability you granted.

Claude Code's security page draws the same conclusion from the other side. Its advice for untrusted content starts with "Avoid piping untrusted content directly to Claude" and "Use virtual machines (VMs) to run scripts and make tool calls, especially when interacting with external web services", and it ends with the warning that "no system is completely immune to all attacks." A factory cannot stop reading tickets, so it has to assume some instructions will land and limit what a landed instruction can reach.

### The corpus you will measure against

Stage 01 ships `fixtures/injection-corpus`: 140 synthetic items, 90 attacks across eight techniques (instruction override, role play, fake system messages, tool-result injection, data exfiltration, encoding obfuscation, delimiter escapes and approval spoofs) and 50 benign items, 34 of which mention "ignore" or "system" innocently and 20 of which are long, realistic tool output. Every URL uses `example.invalid` and every secret look-alike is fake. The corpus is labelled with a kind, a technique and an ASI id so you can measure a detector; it is not a benchmark of the world, and lesson 02 explains why its numbers are an upper bound.

## Common pitfalls

- **Treating injection as a prompt problem.** A stronger system prompt changes what the agent tends to do. Assume a fraction of attacks land and design what happens next.
- **Trusting tool output because your own tool produced it.** The tool is yours; the bytes it returns came from a file, a page or a server someone else controls.
- **A threat model without a layer per risk.** "We have a detector" covers ASI01 at the model layer and nothing else. Put each risk on the layer that holds deterministically.
- **Credentials in the agent's environment.** A secret the process can read is a secret an injected command can send. Keep it out rather than guarding it.
- **Forgetting the human.** Forged approvals and confident summaries target the reviewer (ASI09). Approvals have to come from the host, never from text in context.
- **Citing the list from memory.** Secondary sources spell the ASI titles differently; quote the PDF when the wording matters.

## What interviewers ask

**What is the core security problem with a coding agent that reads tickets?**
Text the attacker controls enters the context, and the model cannot reliably separate instructions from data. With tools that run commands, edit files and hold tokens, a followed instruction becomes an action under your credentials. The defence is to assume some instructions land and to make sure the environment and the harness, not the model, decide what an action can reach.

**How do the OWASP agentic and LLM lists relate?**
The agentic list builds on the LLM list. Prompt injection (LLM01) is the entry point and excessive agency (LLM06) is why it matters; OWASP's own appendix says ASI01 combines the two. ASI02 extends LLM06 from model autonomy to misuse of legitimate tools in multi-step plans.

**Why containment before model-layer defences?**
Because model-layer defences are probabilistic and an attacker can retry. Anthropic's phrasing is that the deterministic boundary is what gets hit when everything probabilistic misses. Concretely: no credentials in the sandbox, egress through an allowlist, hooks that deny side effects, and only then a detector or a classifier to reduce how often the boundary is tested.

**Which ASI entry would you add controls for first in a coding factory?**
ASI01 and ASI02 together: goal hijack through tickets and files is the most likely entry, and tool misuse is how it does damage. The first controls are deterministic: deny network commands and writes outside the working tree, block side-effect tools while untrusted content is in context, and keep secrets out of the process. ASI09 comes right after, because forged approvals aim at the reviewer.

## Sources

- [OWASP Top 10 for Agentic Applications for 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), OWASP GenAI Security Project, 2025-12-09, and the PDF linked from that page (sections ASI01, ASI02, ASI05, ASI06, Appendix A), checked 2026-10-17
- [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/llm-top-10/), checked 2026-10-17
- [How we contain Claude across products](https://www.anthropic.com/engineering/how-we-contain-claude), Anthropic Engineering, 2026-05-25, checked 2026-10-17
- [Claude Code security](https://code.claude.com/docs/en/security), sections Protect against prompt injection and MCP security, checked 2026-10-17
- Course code (repository files, not web sources): `course/m5-injection-lab/README.md`, `course/m5-injection-lab/starter/src/injection_lab/types.py`, `fixtures/injection-corpus/README.md`
