import asyncio
import uuid

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultError,
    ResultMessage,
    TextBlock,
)
from harness_lab_lessons import run_resuming

STALE = "3f6c1b2a-9d4e-4c7b-8a1f-0e2d5c6b7a89"
FRESH = "8d0e7a41-52c3-4f9b-b6e2-1a7c9d3f5e60"
store = {"001-discount-rounding": STALE}


async def scripted_query(prompt, options):
    if options.resume == STALE:
        missing = f"No conversation found with session ID: {STALE}"
        raise ResultError(
            f"Claude Code returned an error result: {missing}",
            {"subtype": "error_during_execution", "errors": [missing], "session_id": STALE},
            exit_code=1,
        )
    yield AssistantMessage([TextBlock("Reading the ticket again from the start.")], model="m")
    yield ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=FRESH,
        terminal_reason="completed",
    )


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


options = ClaudeAgentOptions(cwd="/work/tinyshop", resume=store["001-discount-rounding"])
run = asyncio.run(run_resuming("Fix ticket 001.", options, scripted_query))
for number, attempt in enumerate(run.attempts, 1):
    print(f"attempt {number}: resume={attempt.resume} -> {attempt.outcome}")

result = run.messages[-1]
store["001-discount-rounding"] = result.session_id
print("result:", result.subtype, "new session:", result.session_id)
print("store now:", store)
print("valid session_id values:", {v: is_uuid(v) for v in ("ticket-001", FRESH)})
