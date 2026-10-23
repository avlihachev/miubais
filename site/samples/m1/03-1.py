import json

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions
from harness_lab_lessons import review_verdict_schema

WRITERS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"}

reviewer = AgentDefinition(
    description="Checks a finished ticket diff for bugs. Use once the fix is in place.",
    prompt=(
        "Inspect the uncommitted changes in this repository and the code they touch. "
        "Do not change any file. For each problem give file, line, severity and a short note, "
        "and approve only if you found nothing critical or important."
    ),
    tools=["Read", "Grep", "Glob"],
    model="sonnet",
    maxTurns=8,
)
options = ClaudeAgentOptions(
    cwd="/work/tinyshop",
    agents={"diff-reviewer": reviewer},
    allowed_tools=["Read", "Grep", "Glob", "Agent"],
    permission_mode="dontAsk",
    setting_sources=[],
    max_budget_usd=0.30,
    output_format={"type": "json_schema", "schema": review_verdict_schema()},
)

try:
    AgentDefinition(description="d", prompt="p", max_turns=8)
except TypeError as err:
    print("snake_case field:", err)

print("agents:", list(options.agents))
print("reviewer tools:", reviewer.tools, "max turns:", reviewer.maxTurns, "model:", reviewer.model)
print("write-capable tools:", sorted(WRITERS & set(reviewer.tools)))
print("output_format type:", options.output_format["type"])
print(json.dumps(options.output_format["schema"], indent=2))
