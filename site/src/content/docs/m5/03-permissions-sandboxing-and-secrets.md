---
title: Permissions, sandboxing and secrets
description: The order in which the Agent SDK evaluates a tool call, why dontAsk and bare-name deny rules suit an unattended agent, what Claude Code's Bash sandbox restricts and what runs outside it, why credentials should never enter the process, and how the course scrubs tool output and builds subprocess environments from an allowlist.
module: m5
order: 3
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:mcp": "2.3.0"
  "model:default": claude-opus-5-5
sources:
  - url: https://code.claude.com/docs/en/agent-sdk/permissions
    title: Configure permissions
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/hooks
    title: Intercept and control agent behavior with hooks
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/sandboxing
    title: Configure the sandboxed Bash tool
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/env-vars
    title: Environment variables
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://www.anthropic.com/engineering/how-we-contain-claude
    title: How we contain Claude across products
    published: 2026-05-25
    checked: 2026-10-17
---

**Prerequisites:** [lesson 02](../02-indirect-injection-and-provenance/), whose taint policy runs as one of the hooks this lesson places in the permission order.

## Why this matters for the factory

Lesson 02 assumed a hook can deny a tool call. This lesson is about everything around that hook: the order in which the Agent SDK decides, the operating-system boundary Claude Code can put around shell commands, and the secrets that sit in the process environment whatever the hooks decide. A factory agent runs unattended, so nobody answers a permission prompt, so a rule that relies on a person clicking "deny" does not protect it.

The second reason is credentials. An agent that opens pull requests needs a Git token; one that calls an MCP server needs a bearer token; the process that starts it often has cloud keys in its environment because the CI runner does. Anthropic's containment post puts the goal in one line: "if credentials never enter the sandbox, they can't be exfiltrated". Stage 03 of the exercise is built on that line: scrub secrets out of tool output, and start every subprocess with an environment built from an allowlist instead of the one the parent inherited.

## Core idea

Think of a tool call passing three gates, each owned by a different layer.

1. **The permission pipeline** (harness). Hooks run first and can deny; deny rules come next and hold even in `bypassPermissions`; then ask rules, the permission mode, allow rules and finally the `canUseTool` callback. For an unattended agent, the right ending is `dontAsk`: anything that would have prompted is denied.
2. **The sandbox** (environment). When it is on, a `Bash` command runs inside an OS-enforced boundary that limits writes and network, whatever the command text says. It covers shell commands only.
3. **The environment itself** (environment). Whatever is in the process environment and readable on disk is reachable by a command that slips through. The cheapest control is to not have the secret there.

Then there is the output side: a secret that a tool prints, such as a `.env` file the agent reads or a token echoed in a log, enters the context, the transcript, the audit log and possibly a pull request description. Scrubbing tool output before the model sees it closes that path.

## Mechanics

### The order the SDK evaluates a call

The permissions guide lists the steps: hooks, deny rules, ask rules, permission mode, allow rules, `canUseTool`.
- Hooks first: "A hook can deny the call outright or pass it on. A hook that returns `allow` does not skip the deny and ask rules below." The taint policy from lesson 02 and the M1 path policy are hooks, so they run before anything can approve the call.
- Deny rules are absolute: "If a deny rule matches, the tool is blocked, even in `bypassPermissions` mode." Bare names remove tools entirely: with `disallowed_tools=["Bash"]`, "The `Bash` tool definition is removed from the request. Claude does not see the tool and cannot attempt it." A scoped rule like `Bash(rm *)` keeps `Bash` and denies matching calls "in every permission mode, including `bypassPermissions`", but it matches the command "as written", so `/bin/rm` falls through.
- `dontAsk` turns prompts into denials: "Any call that would otherwise prompt is denied." The guide's recipe for a locked-down agent is to "pair `allowedTools` with `permissionMode: "dontAsk"`". Calls that need no approval still run, "such as read-only Bash commands, tools like `Agent` that don't ask before running, and file reads inside your working directories."
- `allowed_tools` is not a whitelist: "`allowed_tools` does not constrain `bypassPermissions`." Setting `allowed_tools=["Read"]` with `bypassPermissions` "still approves every tool, including `Bash`, `Write`, and `Edit`."

When several `PreToolUse` hooks answer, "`deny` takes priority over `defer`, which takes priority over `ask`, which takes priority over `allow`." Hooks registered under separate matchers run in parallel, so do not write one that relies on another having run first; the exercise's `compose` runs the taint policy and the M1 policy in sequence inside one callback for that reason. And a slow hook is safe in the right direction: when a `PreToolUse` callback exceeds its timeout, "Claude Code blocks the tool call" (since v2.1.210; before that, it was reported as a user rejection).

### The Bash sandbox: what it restricts

Claude Code's sandbox is "a boundary that the operating system enforces around the shell commands Claude runs." On macOS it "uses the built-in Seatbelt framework"; on Linux and WSL2 it "relies on `bubblewrap` and `socat`". It is off by default: "To turn it on, run `/sandbox` in a session ... or set `sandbox.enabled` to `true`." The defaults the page lists:

| Access | Default while sandboxed |
| --- | --- |
| Writes | The working directory, a per-user temp directory, and directories you've added |
| Reads | "Most of the machine, including credential files such as `~/.ssh` and `~/.aws/credentials`" unless you add `filesystem.denyRead` or `credentials` entries |
| Network | "No direct route out", through a local proxy that checks each host against allowed domains, "which start empty" |
| Environment variables | "Inherited from Claude Code, including any secrets in its environment" |

A sandboxed `cat ~/.aws/credentials` works by default; what stops the exfiltration is the network row. The `sandbox.credentials` setting fixes both: entries with `"mode": "deny"` deny reads of the listed files and "environment variables are unset before each sandboxed command runs." Claude Code builds the sandbox on the open-source `@anthropic-ai/sandbox-runtime` package, which is why the containment post calls the boundary auditable.

### What runs outside it

"The sandbox covers shell commands only. Claude's file tools, MCP servers, and hooks run outside it." The page is specific: built-in file and web tools "such as Read, Edit, Write, WebFetch, and WebSearch follow permission rules instead. A `denyRead` entry doesn't stop the Read tool, and `allowedDomains` doesn't limit WebFetch"; command hooks, local MCP servers, LSP servers and helper commands "run with your full access"; commands you exclude, commands typed at the `!` prompt and unsandboxed retries also run outside. To put all of it behind one boundary, the page says to run the Claude Code process itself in a container, a VM or the sandbox runtime.

For the course this splits the work. The sandbox handles a `curl` that slips past the command rules. Hooks and permission rules handle `Read` of a secret file and `WebFetch` to an attacker's host. And the remote MCP server in lesson 04 runs in its own process, so its own authorization has to hold.

### Keeping credentials out

There are two environment knobs, and they are not the same thing. Claude Code has `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`: "Set to `1` to strip credentials from the environments of the subprocesses Claude Code starts, such as Bash commands, hooks, and stdio MCP servers." It recognises credentials "by its variable name or its value, and it leaves GitHub tokens and proxy settings in place". That last clause matters for a factory whose agent holds a GitHub token. The exercise's harness does not set it: it is a Claude Code setting rather than an Agent SDK guarantee and it keeps GitHub tokens, so the harness relies on its own output scrubbing and subprocess allowlist, and you can still add the variable on top.

The Agent SDK's `env` option is the other knob, and it does not remove anything: it is "merged on top of the inherited process environment" (Agent SDK reference - Python). Passing a small `env` does not hide the parent's variables from Claude Code. So the exercise does two things. `secrets.subprocess_env(extra)` returns only `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR` and `TERM` from the environment plus what you pass explicitly, for subprocesses your own code starts; `secrets.guard_env(options)` sets the options' `env` to that allowlist, which narrows what you add but not what is inherited. The real fix is upstream: start the harness process without the secret, and hand the agent a short-lived, narrowly scoped token for the one service it needs.

### Scrubbing tool output

`secrets.scrub(text)` replaces Anthropic keys, Langfuse keys, AWS access key ids, GitHub `ghp_` and `github_pat_` tokens, private key blocks, JWTs, the token after `Bearer` (when it is token-shaped, so "Bearer authentication" in prose stays), and the value of `.env`-style, YAML, INI or JSON pairs whose name looks like a secret, with `[REDACTED:<kind>]`, keeping the name so the output still makes sense. It looks inside nested, escaped JSON strings and decodes base64 blobs and long hex runs to see whether they hold a key. It misses a key split across lines or string concatenation, a key with a zero-width character inside it, and base64 of base64. The tests check the other direction too: the whole corpus and 200 seeded random strings must come back byte for byte, because a scrubber that mangles ordinary output breaks the agent's work. `scrub_hook` runs it as a `PostToolUse` hook and, like the provenance hook, fails closed. The sample runs the lesson's smaller scrubber on clearly fake values.

Sample: `site/samples/m5/03-1.py`.

```python
import base64
import json

from injection_lab_lessons import minimal_env, toy_scrub

fake_key = "sk-ant-api03-" + "EXAMPLE" * 3
blob = base64.b64encode(f"ANTHROPIC_API_KEY={fake_key}".encode()).decode()
outputs = [
    f"ANTHROPIC_API_KEY={fake_key}",
    "aws_access_key_id = AKIAIOSFODNN7EXAMPLE",
    "curl -H 'Authorization: Bearer not-a-real-token-123' https://api.example.invalid",
    json.dumps({"log": json.dumps({"GITHUB_TOKEN": "ghp_" + "0" * 36})}),
    f"cache entry: {blob}",
    "GET /search?token=page2&sort=asc 200",
]
for text in outputs:
    red = toy_scrub(text)
    print(red.text[:72], red.counts)

parent = {"PATH": "/usr/bin", "HOME": "/home/dev", "AWS_SECRET_ACCESS_KEY": "fake", "CI": "1"}
print("subprocess env:", sorted(minimal_env(parent, {"PYTHONHASHSEED": "0"})))
```

Output, run on 2026-10-17:

```
ANTHROPIC_API_KEY=[REDACTED:anthropic-key] {'anthropic-key': 1}
aws_access_key_id = [REDACTED:aws-access-key] {'aws-access-key': 1}
curl -H 'Authorization: Bearer [REDACTED:bearer-token]' https://api.exam {'bearer-token': 1}
{"log": "{\"GITHUB_TOKEN\": \"[REDACTED:github-token]\"}"} {'github-token': 1}
cache entry: [REDACTED:anthropic-key] {'anthropic-key': 1}
GET /search?token=page2&sort=asc 200 {}
subprocess env: ['HOME', 'PATH', 'PYTHONHASHSEED']
```

Every value here is a fake with the right shape. In the fourth line the token sits inside a JSON string inside another JSON string, with escaped quotes, and is still found. The fifth line is a base64 cache entry that decodes to `ANTHROPIC_API_KEY=sk-ant-…`, which a plain pattern pass would miss. The sixth is the negative case: `token=page2` in a query string is a pagination parameter and stays. The last line is the subprocess environment: the AWS secret and `CI` from the parent are gone, `PYTHONHASHSEED` is there because it was passed explicitly.

## Common pitfalls

- **Relying on prompts in an unattended run.** Nobody answers them. Use `dontAsk`, deny rules and hooks.
- **`allowed_tools` as a whitelist.** It pre-approves; it does not hide the rest, and it does not constrain `bypassPermissions`. Remove tools by bare name in `disallowed_tools`.
- **Assuming the sandbox covers file tools.** It covers shell commands. `Read` of `~/.ssh` is a permission-rule problem.
- **Sandbox on, credentials readable.** Reads cover most of the machine by default; add `credentials` deny entries or keep the files off the machine.
- **Believing `env` replaces the environment.** It merges on top. Keep secrets out of the parent process.
- **A scrubber that only matches plain text.** Secrets arrive escaped, nested and encoded; test those shapes, and test that ordinary text is left alone.

## What interviewers ask

**In what order does the Agent SDK decide whether a tool call runs?**
Hooks, deny rules, ask rules, permission mode, allow rules, then `canUseTool`. Hooks can deny before anything approves; deny rules hold even in `bypassPermissions`; a bare-name deny removes the tool from the request. For an unattended agent, `dontAsk` denies anything that would have prompted.

**Is turning on Claude Code's sandbox enough to stop credential theft?**
No. It is OS-enforced and blocks network by default, which stops the classic exfiltration, but reads cover most of the machine including `~/.ssh` and `~/.aws/credentials` unless you deny them, environment variables are inherited, and file tools, hooks and MCP servers run outside it. Deny credential paths, scrub the environment, and best of all keep credentials out of the machine the agent runs on.

**How do you keep secrets out of an agent's context?**
Two directions. Inbound to the process: start it with an allowlisted environment and short-lived scoped tokens, because the SDK's `env` merges on top of the inherited environment. Outbound from tools: scrub tool output in a `PostToolUse` hook that handles nested JSON and encoded blobs, fails closed, and is tested against ordinary text so it does not corrupt work.

**Why put a security check in a hook rather than in the system prompt?**
A hook is code the model cannot argue with: it runs before deny and allow rules, a deny from it applies even in `bypassPermissions`, and a timed-out `PreToolUse` hook blocks the call. A system prompt changes what the model tends to do; it is a model-layer defence.

## Sources

- [Configure permissions](https://code.claude.com/docs/en/agent-sdk/permissions), sections How permissions are evaluated, Allow and deny rules, Permission modes, Claude Agent SDK docs, checked 2026-10-17
- [Intercept and control agent behavior with hooks](https://code.claude.com/docs/en/agent-sdk/hooks), sections Outputs, Register multiple hooks, Hook timeout, checked 2026-10-17
- [Configure the sandboxed Bash tool](https://code.claude.com/docs/en/sandboxing), sections What the sandbox restricts, What runs outside the sandbox, Protect credentials, checked 2026-10-17
- [Environment variables](https://code.claude.com/docs/en/env-vars), `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`, checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), `ClaudeAgentOptions.env`, checked 2026-10-17
- [How we contain Claude across products](https://www.anthropic.com/engineering/how-we-contain-claude), Anthropic Engineering, 2026-05-25, checked 2026-10-17
- Course code (repository files, not web sources): stage 03 in `course/m5-injection-lab/README.md` and `tests/test_03_secrets_and_env.py`, `fixtures/harnesskit/src/harnesskit/policy.py`, the lesson helpers in `course/m5-injection-lab/lesson_support/src/injection_lab_lessons/`
