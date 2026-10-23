import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "course/m0-cost-lab/starter/src"))

from cost_lab.transport import FixtureExhausted, make_client

MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-opus-5-5",
    "content": [{"type": "text", "text": "hi"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 5, "output_tokens": 1},
}


def ask(client, text):
    return client.messages.create(
        model="claude-opus-5-5",
        max_tokens=16,
        messages=[{"role": "user", "content": text}],
    )


def test_recorded_transport_replays_and_records(tmp_path):
    (tmp_path / "hello.json").write_text(
        json.dumps({"status": 200, "headers": {}, "body": MESSAGE})
    )
    client, t = make_client(tmp_path, ["hello"])
    msg = ask(client, "x")
    assert msg.content[0].text == "hi"
    assert t.requests[0].body["messages"][0]["content"] == "x"
    with pytest.raises(FixtureExhausted):
        ask(client, "y")


def test_body_text_fixture_keeps_headers(tmp_path):
    (tmp_path / "sse.json").write_text(
        json.dumps(
            {
                "status": 200,
                "headers": {"content-type": "text/event-stream"},
                "body_text": "event: ping\ndata: {}\n\n",
            }
        )
    )
    _, t = make_client(tmp_path, ["sse"])
    import httpx2

    response = httpx2.Client(transport=t).post("http://x/v1/messages")
    assert response.headers["content-type"] == "text/event-stream"
    assert response.text.startswith("event: ping")
    assert t.requests[0].body == {}
