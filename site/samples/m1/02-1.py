import asyncio
import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from harness_lab_lessons import decide, deny

ROOTS = [Path("/work/tinyshop/src")]


async def guard(input_data, tool_use_id, context):
    event = input_data.get("hook_event_name", "PreToolUse")
    try:
        ruling = decide(
            input_data["tool_name"],
            input_data.get("tool_input") or {},
            ROOTS,
            cwd=Path(input_data["cwd"]),
        )
    except Exception as exc:  # noqa: BLE001
        return deny(event, f"guard error: {exc}")
    return {} if ruling.allowed else deny(event, ruling.reason)


def pre_tool_use(tool_name: str, tool_input: dict) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "11111111-2222-4333-8444-555555555555",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": "/work/tinyshop",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "toolu_01",
    }


edit = pre_tool_use(
    "Edit",
    {
        "file_path": "/work/tinyshop/src/tinyshop/pricing.py",
        "old_string": "round(cents)",
        "new_string": "cents.quantize(CENT, rounding=ROUND_HALF_UP)",
    },
)
push = pre_tool_use("Bash", {"command": "git push origin main"})
for event in (edit, push):
    returned = asyncio.run(guard(event, event["tool_use_id"], None))
    print(event["tool_name"], "->", json.dumps(returned))

matcher = HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit|Bash", hooks=[guard], timeout=30)
options = ClaudeAgentOptions(
    cwd="/work/tinyshop",
    allowed_tools=["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
    disallowed_tools=["WebFetch", "Bash(git push *)"],
    permission_mode="dontAsk",
    hooks={"PreToolUse": [matcher]},
    setting_sources=[],
)
print("matcher:", matcher.matcher, "timeout:", matcher.timeout, "callbacks:", len(matcher.hooks))
print("mode:", options.permission_mode, "denied:", options.disallowed_tools)
print("settings loaded:", options.setting_sources)
