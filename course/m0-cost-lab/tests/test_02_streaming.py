import json

import pytest
from cost_lab.streaming import TruncatedError, stream_final

PARAMS = {
    "model": "claude-opus-5-5",
    "max_tokens": 1000,
    "messages": [{"role": "user", "content": "A1?"}],
}


def events(fixture_dir, name):
    text = json.loads((fixture_dir / f"{name}.json").read_text())["body_text"]
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def deltas(fixture_dir, name):
    return [
        e["delta"]["text"]
        for e in events(fixture_dir, name)
        if e["type"] == "content_block_delta" and e["delta"]["type"] == "text_delta"
    ]


def test_stream_forwards_chunks_and_returns_final(client_for, fixture_dir):
    client, t = client_for(["stream_ok"])
    chunks = []
    final = stream_final(client, on_text=chunks.append, **PARAMS)
    expected = deltas(fixture_dir, "stream_ok")
    assert len(expected) > 1 and chunks == expected
    assert "".join(chunks) == final.content[0].text
    last = next(e for e in events(fixture_dir, "stream_ok") if e["type"] == "message_delta")
    assert final.usage.output_tokens == last["usage"]["output_tokens"]
    assert t.requests[0].body["stream"] is True


def test_stream_without_callback_still_returns_final(client_for):
    client, _ = client_for(["stream_ok"])
    assert stream_final(client, **PARAMS).stop_reason == "end_turn"


def test_stream_truncated_raises_with_partial(client_for, fixture_dir):
    client, _ = client_for(["stream_truncated"])
    with pytest.raises(TruncatedError) as e:
        stream_final(client, **PARAMS)
    assert e.value.partial_text == "".join(deltas(fixture_dir, "stream_truncated"))
