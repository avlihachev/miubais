from collections.abc import Iterable
from typing import Any, Literal

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from pydantic import BaseModel, ConfigDict

Role = Literal["user", "assistant", "tool", "result"]


class TraceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    role: Role
    text: str | None = None
    tool: str | None = None
    input: dict[str, Any] | None = None
    output: str | None = None
    subtype: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None
    message_id: str | None = None


def _output_text(content: Any) -> str:
    if content is None or isinstance(content, str):
        return content or ""
    return "\n".join(
        part.get("text", "") for part in content if isinstance(part, dict) and "text" in part
    )


def _entries(messages: Iterable[Any]) -> Iterable[dict[str, Any]]:
    tools: dict[str, str] = {}
    for message in messages:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    yield {
                        "role": "assistant",
                        "text": block.text,
                        "message_id": message.message_id,
                    }
                elif isinstance(block, ToolUseBlock):
                    tools[block.id] = block.name
                    yield {
                        "role": "assistant",
                        "tool": block.name,
                        "input": block.input,
                        "message_id": message.message_id,
                    }
        elif isinstance(message, UserMessage):
            if isinstance(message.content, str):
                yield {"role": "user", "text": message.content}
                continue
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    yield {
                        "role": "tool",
                        "tool": tools.get(block.tool_use_id),
                        "output": _output_text(block.content),
                    }
                elif isinstance(block, TextBlock):
                    yield {"role": "user", "text": block.text}
        elif isinstance(message, ResultMessage):
            yield {
                "role": "result",
                "subtype": message.subtype,
                "cost_usd": message.total_cost_usd,
                "num_turns": message.num_turns,
            }


def to_trace_lines(messages: Iterable[Any]) -> list[TraceLine]:
    return [TraceLine(n=n, **entry) for n, entry in enumerate(_entries(messages), 1)]
