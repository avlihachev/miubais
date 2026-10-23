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
