import dataclasses
import json
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultError,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


def is_error_result(message: Any) -> bool:
    return isinstance(message, ResultMessage) and message.is_error


def result_error(result: ResultMessage) -> ResultError:
    data = {"type": "result", **dataclasses.asdict(result)}
    detail = "; ".join(result.errors or []) or (result.result or "").strip() or result.subtype
    return ResultError(f"Claude Code returned an error result: {detail}", data=data, exit_code=1)


def scripted_query(
    items: Iterable[Any], *, raise_after_error: bool = True
) -> Callable[..., AsyncIterator[Any]]:
    script = list(items)

    async def replay(options: Any) -> AsyncIterator[Any]:
        for item in script:
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                await item(options)
                continue
            yield item
            if raise_after_error and is_error_result(item):
                raise result_error(item)

    def query(prompt: Any = None, options: Any = None, **_: Any) -> AsyncIterator[Any]:
        return replay(options)

    return query


@dataclasses.dataclass
class Timed:
    at_ms: int
    message: Any


def _block_from(raw: dict[str, Any]) -> Any:
    if raw["type"] == "text":
        return TextBlock(text=raw["text"])
    if raw["type"] == "tool_use":
        return ToolUseBlock(id=raw["id"], name=raw["name"], input=raw["input"])
    if raw["type"] == "thinking":
        return ThinkingBlock(thinking=raw["thinking"], signature=raw["signature"])
    return ToolResultBlock(
        tool_use_id=raw["tool_use_id"], content=raw.get("content"), is_error=raw.get("is_error")
    )


def _block_to(block: Any) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "thinking": block.thinking, "signature": block.signature}
    return {
        "type": "tool_result",
        "tool_use_id": block.tool_use_id,
        "content": block.content,
        "is_error": block.is_error,
    }


def _content_from(content: Any) -> Any:
    return content if isinstance(content, str) else [_block_from(b) for b in content]


def _content_to(content: Any) -> Any:
    return content if isinstance(content, str) else [_block_to(b) for b in content]


def _message_from(record: dict[str, Any]) -> Any:
    kind = record["type"]
    if kind == "assistant":
        return AssistantMessage(
            content=[_block_from(b) for b in record["content"]],
            model=record["model"],
            usage=record.get("usage"),
            message_id=record.get("message_id"),
            stop_reason=record.get("stop_reason"),
        )
    if kind == "user":
        return UserMessage(content=_content_from(record["content"]))
    if kind == "system":
        return SystemMessage(subtype=record["subtype"], data=record["data"])
    if kind == "result":
        return ResultMessage(
            subtype=record["subtype"],
            duration_ms=record["duration_ms"],
            duration_api_ms=record["duration_api_ms"],
            is_error=record["subtype"] != "success",
            num_turns=record["num_turns"],
            session_id=record["session_id"],
            total_cost_usd=record.get("total_cost_usd"),
            usage=record.get("usage"),
            model_usage=record.get("model_usage"),
        )
    raise ValueError(f"unknown record type: {kind}")


def _record_from(item: Timed) -> dict[str, Any]:
    message = item.message
    if isinstance(message, dict):
        return {"t_ms": item.at_ms, **message}
    if isinstance(message, AssistantMessage):
        return {
            "t_ms": item.at_ms,
            "type": "assistant",
            "model": message.model,
            "message_id": message.message_id,
            "stop_reason": message.stop_reason,
            "usage": message.usage,
            "content": [_block_to(b) for b in message.content],
        }
    if isinstance(message, UserMessage):
        return {
            "t_ms": item.at_ms,
            "type": "user",
            "content": _content_to(message.content),
        }
    if isinstance(message, SystemMessage):
        return {
            "t_ms": item.at_ms,
            "type": "system",
            "subtype": message.subtype,
            "data": message.data,
        }
    return {
        "t_ms": item.at_ms,
        "type": "result",
        "subtype": message.subtype,
        "num_turns": message.num_turns,
        "session_id": message.session_id,
        "duration_ms": message.duration_ms,
        "duration_api_ms": message.duration_api_ms,
        "total_cost_usd": message.total_cost_usd,
        "usage": message.usage,
        "model_usage": message.model_usage,
    }


def load_run(path: Path) -> list[Timed]:
    timed = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record["type"] == "meta":
            timed.append(Timed(0, {k: v for k, v in record.items() if k != "t_ms"}))
        else:
            timed.append(Timed(record["t_ms"], _message_from(record)))
    return timed


def dump_run(path: Path, timed: Iterable[Timed]) -> None:
    lines = (json.dumps(_record_from(item), separators=(",", ":")) for item in timed)
    Path(path).write_text("".join(f"{line}\n" for line in lines))
