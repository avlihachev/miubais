import json
from dataclasses import dataclass

DONE = "data: [DONE]"


@dataclass(frozen=True)
class Tally:
    content_tokens: int
    reasoning_chunks: int
    ttft_ms: float | None
    first_reasoning_ms: float | None
    tps: float | None
    finish_reason: str | None
    usage_completion_tokens: int | None
    done: bool
    text: str


def chunk(delta: dict, finish_reason: str | None = None) -> str:
    choice = {"index": 0, "delta": delta, "finish_reason": finish_reason}
    return "data: " + json.dumps({"object": "chat.completion.chunk", "choices": [choice]})


def usage_chunk(prompt_tokens: int, completion_tokens: int) -> str:
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return "data: " + json.dumps({"object": "chat.completion.chunk", "choices": [], "usage": usage})


def tally(arrivals: list[tuple[float, str]], sent_ms: float = 0.0) -> Tally:
    token_times: list[float] = []
    reasoning_times: list[float] = []
    text: list[str] = []
    finish = None
    usage = None
    done = False
    for at_ms, line in arrivals:
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            done = True
            break
        event = json.loads(payload)
        if event.get("usage"):
            usage = event["usage"].get("completion_tokens")
        for choice in event.get("choices", []):
            delta = choice.get("delta") or {}
            if delta.get("content"):
                token_times.append(at_ms)
                text.append(delta["content"])
            if delta.get("reasoning") or delta.get("reasoning_content"):
                reasoning_times.append(at_ms)
            finish = choice.get("finish_reason") or finish
    span_ms = token_times[-1] - token_times[0] if token_times else 0.0
    return Tally(
        content_tokens=len(token_times),
        reasoning_chunks=len(reasoning_times),
        ttft_ms=token_times[0] - sent_ms if token_times else None,
        first_reasoning_ms=reasoning_times[0] - sent_ms if reasoning_times else None,
        tps=len(token_times) / (span_ms / 1000) if span_ms > 0 else None,
        finish_reason=finish,
        usage_completion_tokens=usage,
        done=done,
        text="".join(text),
    )
