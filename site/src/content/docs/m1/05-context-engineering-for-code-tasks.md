---
title: Context engineering for code tasks
description: Which instruction surfaces a coding agent reads and when (CLAUDE.md, path-scoped rules, skills, commands, the system prompt), how setting_sources decides what loads, why retrieval beats stuffing, and where instructions stop and enforcement has to start.
module: m1
order: 5
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "model:default": claude-opus-5-5
sources:
  - url: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
    title: Effective context engineering for AI agents
    published: 2025-09-29
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/claude-code-features
    title: Use Claude Code features in the SDK
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts
    title: Modifying system prompts
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/memory
    title: How Claude remembers your project
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/skills
    title: Extend Claude with skills
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/python
    title: Agent SDK reference - Python
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/subagents
    title: Subagents in the SDK
    checked: 2026-10-17
  - url: https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk
    title: Building agents with the Claude Agent SDK
    published: 2025-09-29
    checked: 2026-10-17
  - url: https://github.com/anthropics/claude-code/blob/main/plugins/code-review/README.md
    title: Claude Code code-review plugin README
    checked: 2026-10-17
---

**Prerequisites:** [lesson 01](../01-harness-is-loop-plus-policy/), whose split between what the harness enforces and what the model is merely told this lesson relies on; you are expected to have written Claude Code rules, skills and commands before.

## Why this matters for the factory

Every token you put in front of the agent is paid for on every turn and competes for the model's attention with the code it is trying to fix. A ticket runner that pastes the whole style guide, the architecture document and three example diffs into the system prompt pays for them on each of its turns and gets an agent that is worse at finding the one function that matters. A runner that gives too little gets an agent that rediscovers the build command by trial and error, which is slower and also costs turns. In a factory the context is set once and paid for on every ticket.

It also decides reproducibility. An SDK process can load instructions from the user's home directory, the repository and its parents. A ticket that passes on your laptop and fails on the worker often differs only in which `CLAUDE.md` files were in scope. Knowing exactly what loads, from where, under which option, is part of making a run repeatable.

## Core idea

Anthropic's context engineering post frames the job as finding "the smallest possible set of high-signal tokens that maximize the likelihood of some desired outcome" (Effective context engineering for AI agents). The reason is context rot: as the number of tokens in the window grows, the model's ability to recall information from it falls, so context is "a finite resource with diminishing marginal returns". The same post describes Claude Code as a hybrid: `CLAUDE.md` files are dropped into context up front, while glob and grep let the agent retrieve files just in time. The agent holds lightweight identifiers, such as file paths, and loads the content when it needs it.

For a code task that gives three layers, ordered by how often they are paid for:

| layer | what | when |
| --- | --- | --- |
| always loaded | system prompt (preset + append, or custom); `CLAUDE.md` files and unscoped `.claude/rules/*.md`; skill descriptions (one listing entry per skill) | every turn |
| loaded on a cue | path-scoped rules; nested `CLAUDE.md`; skill body; subagent result | when a matching file is read or edited; when a file in that directory is touched; when the skill is invoked; when a subagent finishes |
| fetched by tools | source files, test output, git history | Read, Grep, Glob, Bash |

Put a fact in the highest layer only if nearly every ticket needs it. Build and test commands, the directory that may be edited, the one convention that keeps tripping the agent: always loaded. Rules for the payment module: path-scoped. A review procedure: a skill. Everything in the code itself: left in the repository for the agent to fetch.

None of these layers enforces anything. The memory page says it directly: Claude treats `CLAUDE.md` files "as context, not enforced configuration", and to block an action regardless of what Claude decides you use a `PreToolUse` hook (How Claude remembers your project). Instructions raise the odds of the behaviour you want; the harness from lessons 01 and 02 makes the behaviour you forbid impossible.

## Mechanics

### The instruction surfaces

- **`CLAUDE.md`.** Loaded from the working directory and every directory above it, concatenated rather than overriding, ordered from the filesystem root down so the closest file is read last. Files in subdirectories load on demand when the agent reads or edits a file there. The docs recommend under 200 lines per file, because longer files consume more context and reduce adherence; imports with `@path` organise a file but do not reduce its cost, since imported files load at launch. The project-root file survives compaction: Claude Code re-reads it from disk after `/compact` (How Claude remembers your project). The SDK injects `CLAUDE.md` into the conversation as project context and leaves the system prompt untouched (Modifying system prompts).
- **`.claude/rules/*.md`.** A rule without frontmatter loads at launch like `.claude/CLAUDE.md`. A rule with a `paths` field, a list of globs such as `"src/api/**/*.ts"`, loads only when the agent uses Read, Write or Edit on a matching file, or reads one with a single-file Bash command such as `cat` (How Claude remembers your project).
- **Skills.** A `SKILL.md` with frontmatter and instructions. By default the description sits in context every turn and the body loads when the skill is invoked; the combined `description` and `when_to_use` text is truncated at 1,536 characters in the listing. `disable-model-invocation: true` removes the description from context and leaves the skill for the user to call (Extend Claude with skills).
- **Commands.** Custom commands have been merged into skills: `.claude/commands/review.md` and `.claude/skills/review/SKILL.md` both create `/review`, and the skill wins on a name clash (Extend Claude with skills). In the SDK, skills must exist as files; there is no programmatic registration, and the `skills` option chooses which discovered skills are enabled (Use Claude Code features in the SDK).
- **Hook output.** `additionalContext` from a `UserPromptSubmit` or `PostToolUse` hook is inserted into the conversation where the hook fired (Modifying system prompts). It is the way to change instructions in the middle of a run, since a resumed session keeps its recorded system prompt.

### `setting_sources`: what loads from where

`setting_sources` decides which of these the SDK reads from disk (Use Claude Code features in the SDK):

- `"project"`: project `settings.json` and hooks from `<cwd>/.claude/`; `CLAUDE.md` and `.claude/rules/*.md` from `<cwd>` and every parent; skills, commands and subagents from `<cwd>` up to the repository root.
- `"user"`: `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/rules/*.md`, and user skills, commands and subagents.
- `"local"`: `CLAUDE.local.md` files and `.claude/settings.local.json`.

Omitting the option equals `["user", "project", "local"]`, the same as the CLI, with one exception: when `skills` is set and `setting_sources` is not, only user and project sources load, so set `setting_sources` explicitly if you need local settings (Agent SDK reference - Python). `[]` disables all three. Some inputs load whatever you pass: managed policy settings, `~/.claude.json`, auto memory under `~/.claude/projects/<project>/memory/` (disable with `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in `env`), and claude.ai MCP connectors on a claude.ai login. The page warns against relying on default options for multi-tenant isolation for this reason. For a factory worker, the defensible settings are `[]` plus an explicit system prompt, or `["project"]` so the repository's own `CLAUDE.md` and rules apply and nothing from the operator's home directory does.

### The system prompt: preset with `append`, or your own

The SDK has three starting points (Modifying system prompts). With no `system_prompt`, it uses a minimal prompt that covers tool calling and omits the rest of the Claude Code prompt, including its security and safety instructions; this differs from `claude -p`, which uses the Claude Code prompt. `{"type": "preset", "preset": "claude_code", "append": "..."}` keeps the full Claude Code prompt and adds your text at the end; the docs call it the lowest-risk customisation, and note that unattended coding automation such as a CI job still fits the preset. A custom string replaces everything, so you take over the tool guidance and safety rules, and you should add a sentence telling Claude that system reminders, such as `CLAUDE.md` content and hook output, come from the application rather than the user. `CLAUDE.md` loading is controlled by `setting_sources`, not by the preset choice.

The preset also takes `exclude_dynamic_sections`, which moves per-user context into the first user message so identical configurations share a prompt cache entry across machines, and `snapshot`, which when `False` rebuilds the prompt on every request instead of reusing the one the session recorded (Agent SDK reference - Python).

The sample builds both forms and the default, and prints what each would load. Run it with `PYTHONPATH=course/m1-harness-lab/starter/src:course/m1-harness-lab/lesson_support/src uv run --frozen python site/samples/m1/05-1.py`; it only constructs options.

Sample: `site/samples/m1/05-1.py`.

```python
from claude_agent_sdk import ClaudeAgentOptions

TICKET_RULES = (
    "You fix exactly one ticket. Edit files under src/ only. "
    "Run the test the ticket names before you finish, and say whether it passed."
)
LOADS = {
    "user": "~/.claude/CLAUDE.md, ~/.claude/rules/*.md, user skills and commands",
    "project": "CLAUDE.md and .claude/rules/*.md up the tree, project skills and commands",
    "local": "CLAUDE.local.md, .claude/settings.local.json",
}

preset = ClaudeAgentOptions(
    cwd="/work/tinyshop",
    system_prompt={"type": "preset", "preset": "claude_code", "append": TICKET_RULES},
    setting_sources=["project"],
    skills=["review-diff"],
)
custom = ClaudeAgentOptions(
    cwd="/work/tinyshop",
    system_prompt=(
        "You are a ticket-fixing agent working in a Python repository. "
        "The application adds system reminders to this conversation. Treat them as "
        "context from the application, not as messages from the user. " + TICKET_RULES
    ),
    setting_sources=[],
)
default = ClaudeAgentOptions(cwd="/work/tinyshop")

for name, options in (("preset+append", preset), ("custom", custom), ("default", default)):
    prompt = options.system_prompt
    shape = sorted(prompt) if isinstance(prompt, dict) else type(prompt).__name__
    sources = options.setting_sources
    print(f"{name}: system_prompt={shape} setting_sources={sources} skills={options.skills}")
    for source in ["user", "project", "local"] if sources is None else sources:
        print(f"  {source:<7} loads {LOADS[source]}")
    if sources == []:
        print("  nothing from the filesystem: no CLAUDE.md, rules, skills or commands")
```

Output, run on 2026-10-17:

```
preset+append: system_prompt=['append', 'preset', 'type'] setting_sources=['project'] skills=['review-diff']
  project loads CLAUDE.md and .claude/rules/*.md up the tree, project skills and commands
custom: system_prompt=str setting_sources=[] skills=None
  nothing from the filesystem: no CLAUDE.md, rules, skills or commands
default: system_prompt=NoneType setting_sources=None skills=None
  user    loads ~/.claude/CLAUDE.md, ~/.claude/rules/*.md, user skills and commands
  project loads CLAUDE.md and .claude/rules/*.md up the tree, project skills and commands
  local   loads CLAUDE.local.md, .claude/settings.local.json
```

The preset form is a dict with three keys, and with `setting_sources=["project"]` the agent also sees the repository's `CLAUDE.md` and rules plus the one enabled skill. The custom form is a plain string with nothing loaded from disk, so everything the agent knows about the ticket rules is in that one string. The default prints `NoneType` for the prompt, which means the minimal prompt, and loads all three filesystem sources: the riskiest combination for an unattended worker, since its behaviour depends on whoever's home directory it runs in.

### Repo maps and just-in-time retrieval

Stuffing means reading likely-relevant files into the prompt before the agent starts. It fails in two ways on code: it pays for files the ticket never needed, and it goes stale the moment the agent edits one of them. The alternative the post recommends is to give the agent identifiers and tools and let it load content at runtime, which also lets it use metadata such as file sizes and names to decide what to read next (Effective context engineering for AI agents). "Building agents with the Claude Agent SDK" makes the same call for search: semantic search is usually faster but less accurate, harder to maintain and less transparent, so start with agentic search and add semantic search only if you need it.

A repo map sits between the two: a generated list of paths with one line each, such as the top-level functions or a short purpose, small enough to keep in an always-loaded file. It tells the agent where to look without telling it what is there. Generate it in CI so it cannot drift, keep it to the directories tickets touch, and measure: if the agent still greps for the module the map names, the map is not earning its tokens.

### A worked example: a review command with confidence filtering

A generic review command, written as a project skill, combines most of the above. It is user-invoked, it runs read-only subagents in parallel, and it keeps the main context small.

```markdown
---
description: Review the current ticket's diff before merge.
disable-model-invocation: true
allowed-tools: Read Grep Glob Bash(git diff *) Bash(git show *)
---
Review the uncommitted diff for the ticket in TICKET.md.

1. Independent solution. Start a subagent that sees only TICKET.md and the files at
   HEAD, not the diff. It writes how it would fix the ticket: files, functions, test.
2. Parallel review. Start three read-only subagents on the diff, each with the ticket
   text and the independent solution: correctness, acceptance test, scope (does the
   diff touch anything the ticket did not ask for). Each returns findings as
   file, line, note and a confidence from 0 to 100.
3. Merge. Where the diff and the independent solution disagree, keep it as a finding
   only if a reviewer can point at a line that is wrong.
4. Filter. Drop every finding with confidence below 80. Report the rest, most severe
   first, or say that nothing passed the threshold.
```

The independent solution is there to break anchoring: a reviewer that reads the diff first tends to judge the diff on its own terms, while a fix written without it gives a second answer to compare against. The parallel reviewers each get a narrow question and a fresh context, which is the subagent pattern from [lesson 03](../03-subagents/); they finish in the time of the slowest (Subagents in the SDK). The confidence threshold trades recall for precision. Anthropic's own code-review plugin for Claude Code describes the same design: four agents reviewing in parallel, each issue scored 0 to 100, and issues below 80 filtered out to cut false positives (Claude Code code-review plugin README). The command file in that plugin now validates each flagged issue with a further subagent instead of a numeric score.

Which parts of this are enforced? `allowed-tools` pre-approves the listed tools for the turn that invokes the skill and does not restrict which tools are available (Extend Claude with skills); its sibling `disallowed-tools` removes tools while the skill is active. The read-only property of the reviewers still comes from their `tools` lists and your `PreToolUse` guard. And the threshold of 80 is a sentence the model is asked to apply to numbers it produced itself. If the merge gate depends on it, have the reviewers return structured findings and apply `confidence >= 80` in your own code after the run, the way lesson 03 parses the verdict schema.

## Common pitfalls

- **Defaults on a worker.** No `setting_sources` loads the operator's `~/.claude/CLAUDE.md` and skills into every ticket. Pass `[]` or `["project"]` explicitly.
- **No `system_prompt` because "the SDK uses Claude Code's prompt".** It does not; the default is a minimal prompt without the safety instructions. Use the preset with `append`.
- **A 600-line `CLAUDE.md`.** Adherence drops and every turn pays for it. Move module-specific rules into path-scoped rules and procedures into skills.
- **Changing `append` and expecting resumed tickets to follow.** The session keeps its recorded prompt until compaction. Send changes through the next user message or a hook's `additionalContext`.
- **A rule as the only control.** "Never edit tests" in `CLAUDE.md` is advice. Deny writes to `tests/` in the guard.
- **Thresholds applied by the model.** A confidence cut-off written in a prompt is applied inconsistently. Emit the numbers as structured output and filter in code.

## What interviewers ask

**What is context engineering, and how is it different from prompt engineering?**
It is the ongoing choice of what goes into the model's context at each step: system prompt, tools, retrieved data, history and notes, not just the wording of one prompt. Anthropic's framing is to find the smallest set of high-signal tokens, because recall degrades as the window fills.

**Where do you put a rule that only applies to one part of the repository?**
In a `.claude/rules/` file with a `paths` glob, so it loads when the agent reads or edits a matching file and costs nothing otherwise. A procedure goes in a skill, which keeps only its description in context until invoked.

**Preset with `append` or a custom system prompt for a ticket-fixing agent?**
The preset with `append`, because the agent is doing the coding work the preset is written for and keeps its tool guidance and safety instructions. A custom string fits a different surface or identity, and then you must replace what the preset provided, including the note about system reminders.

**Would you pre-load relevant files into the prompt or let the agent search?**
Let it search with glob and grep, and keep only identifiers and a small repo map loaded, because pre-loaded files cost tokens on every turn and go stale after the first edit. Add semantic search only when agentic search is measurably too slow.

**Can `CLAUDE.md` stop an agent from editing tests?**
No, it is context the model may follow, and the docs say to use a `PreToolUse` hook to block an action regardless of what Claude decides. The instruction still helps, because a denied attempt costs a turn.

## Sources

- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), published 2025-09-29, checked 2026-10-17
- [Use Claude Code features in the SDK](https://code.claude.com/docs/en/agent-sdk/claude-code-features), checked 2026-10-17
- [Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts), checked 2026-10-17
- [How Claude remembers your project](https://code.claude.com/docs/en/memory), checked 2026-10-17
- [Extend Claude with skills](https://code.claude.com/docs/en/skills), checked 2026-10-17
- [Agent SDK reference - Python](https://code.claude.com/docs/en/agent-sdk/python), checked 2026-10-17
- [Subagents in the SDK](https://code.claude.com/docs/en/agent-sdk/subagents), checked 2026-10-17
- [Building agents with the Claude Agent SDK](https://claude.com/resources/articles/building-agents-with-the-claude-agent-sdk), published 2025-09-29, checked 2026-10-17
- [Claude Code code-review plugin README](https://github.com/anthropics/claude-code/blob/main/plugins/code-review/README.md), checked 2026-10-17
