import json
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheCounters:
    total: int
    written: int
    read: int
    uncached: int
    hit_ratio: float


@dataclass(frozen=True)
class BatchOutcome:
    kind: str
    retryable: bool
    text: str | None


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def cached_request(
    *, model: str, max_tokens: int, system: str, tools: list[dict], history: list, user_turn: str
) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "tools": canonical(sorted(tools, key=lambda tool: tool["name"])),
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [*history, {"role": "user", "content": user_turn}],
    }


def prefix_fingerprint(body: dict) -> bytes:
    head = {k: body[k] for k in ("model", "tools", "system") if k in body}
    return json.dumps(head, separators=(",", ":"), ensure_ascii=False).encode()


def cache_counters(usage) -> CacheCounters:
    written = usage.cache_creation_input_tokens or 0
    read = usage.cache_read_input_tokens or 0
    total = usage.input_tokens + written + read
    return CacheCounters(total, written, read, usage.input_tokens, read / total if total else 0.0)


def batch_requests(prompts: dict[str, str], *, model: str, max_tokens: int) -> list[dict]:
    return [
        {
            "custom_id": f"item-{key}",
            "params": {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        }
        for key, prompt in prompts.items()
    ]


def join_batch(keys: list[str], lines: list[dict]) -> dict[str, BatchOutcome]:
    found = {}
    for line in lines:
        result = line.get("result") or {}
        kind = result.get("type", "unknown")
        if kind == "succeeded":
            blocks = result["message"]["content"]
            text = "".join(b["text"] for b in blocks if b["type"] == "text")
            found[line["custom_id"]] = BatchOutcome(kind, False, text)
        elif kind == "errored":
            nested = result["error"].get("error", result["error"])
            retryable = nested.get("type") != "invalid_request_error"
            found[line["custom_id"]] = BatchOutcome(kind, retryable, None)
        else:
            found[line["custom_id"]] = BatchOutcome(kind, kind != "canceled", None)
    missing = BatchOutcome("expired", True, None)
    return {key: found.get(f"item-{key}", missing) for key in keys}


def tool_loop(client, *, execute: Callable[[str, dict], str], max_turns: int = 8, **params):
    messages = list(params.pop("messages"))
    for turn in range(1, max_turns + 1):
        response = client.messages.create(messages=messages, **params)
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return text, turn
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": execute(b.name, b.input),
                    }
                    for b in response.content
                    if b.type == "tool_use"
                ],
            }
        )
    raise RuntimeError("tool loop did not finish")
