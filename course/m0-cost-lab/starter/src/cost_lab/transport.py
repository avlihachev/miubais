import json
from dataclasses import dataclass
from pathlib import Path

import anthropic
import httpx2


class FixtureExhausted(anthropic.AnthropicError):
    pass


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    url: str
    body: dict


class RecordedTransport(httpx2.BaseTransport):
    def __init__(self, fixture_dir: Path, sequence: list[str]):
        self.fixture_dir = Path(fixture_dir)
        self.sequence = list(sequence)
        self.requests: list[RecordedRequest] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        content = request.content
        self.requests.append(
            RecordedRequest(
                request.method, str(request.url), json.loads(content) if content else {}
            )
        )
        if not self.sequence:
            raise FixtureExhausted(f"no fixture left for request {len(self.requests)}")
        name = self.sequence.pop(0)
        fixture = json.loads((self.fixture_dir / f"{name}.json").read_text())
        headers = fixture.get("headers", {})
        if "body_text" in fixture:
            return httpx2.Response(
                fixture["status"],
                headers=headers,
                content=fixture["body_text"].encode(),
                request=request,
            )
        return httpx2.Response(
            fixture["status"], headers=headers, json=fixture["body"], request=request
        )


def make_client(
    fixture_dir: Path, sequence: list[str]
) -> tuple[anthropic.Anthropic, RecordedTransport]:
    transport = RecordedTransport(fixture_dir, sequence)
    client = anthropic.Anthropic(
        api_key="recorded", http_client=httpx2.Client(transport=transport), max_retries=0
    )
    return client, transport
