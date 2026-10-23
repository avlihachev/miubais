import json
from pathlib import Path

import anyio
import httpx2
import pytest
from conftest import LAB, TINYSHOP
from injection_lab import mcpserver
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import ProtectedResourceMetadata
from mcp.shared.exceptions import MCPError

RESOURCE = "https://shop.example.invalid/mcp"
ISSUER = "https://auth.example.invalid"
BASE = "http://127.0.0.1:8790"
URL = f"{BASE}/mcp"
TOKENS = LAB / "tests" / "TOKENS.yaml"
METADATA_URL = "https://shop.example.invalid/.well-known/oauth-protected-resource/mcp"
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def build():
    return mcpserver.build(TOKENS, resource=RESOURCE, issuer=ISSUER, tickets=TINYSHOP / "tickets")


def serve(server, steps):
    asgi = mcpserver.app(server)

    async def main():
        async with server.session_manager.run():
            return await steps(asgi)

    return anyio.run(main)


def client(asgi, token=None, responses=None):
    hooks = {"response": [_record(responses)]} if responses is not None else {}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=asgi), headers=headers, event_hooks=hooks
    )


def _record(responses):
    async def hook(response):
        responses.append(response)

    return hook


async def in_session(asgi, token, fn, responses=None):
    async with (
        client(asgi, token, responses) as http,
        streamable_http_client(URL, http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        return await fn(session)


def leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in leaves(inner)]
    return [error]


def params(header):
    scheme, _, rest = header.partition(" ")
    assert scheme == "Bearer"
    parts = (item.strip().partition("=") for item in rest.split(","))
    return {key: value.strip('"') for key, _, value in parts}


def raw_post(token=None, url=URL):
    async def steps(asgi):
        async with client(asgi, token) as http:
            return await http.post(url, json=LIST, headers={"Accept": "application/json"})

    return serve(build(), steps)


def test_valid_token_lists_tools_and_reads_a_ticket():
    async def steps(asgi):
        tools = await in_session(asgi, "tok-read-valid", lambda s: s.list_tools())
        ticket = await in_session(
            asgi, "tok-read-valid", lambda s: s.call_tool("ticket_lookup", {"ticket_id": "001"})
        )
        return tools, ticket

    tools, ticket = serve(build(), steps)
    assert {t.name for t in tools.tools} == {"ticket_lookup", "inventory_reserve"}
    assert not ticket.is_error
    expected = (TINYSHOP / "tickets" / "001-discount-rounding.md").read_text()
    assert ticket.content[0].text == expected


def test_unknown_ticket_is_a_tool_error():
    async def steps(asgi):
        return await in_session(
            asgi, "tok-read-valid", lambda s: s.call_tool("ticket_lookup", {"ticket_id": "999"})
        )

    assert serve(build(), steps).is_error


def test_read_only_token_cannot_reserve_and_gets_a_scope_challenge():
    responses: list = []

    async def steps(asgi):
        try:
            await in_session(
                asgi,
                "tok-read-valid",
                lambda s: s.call_tool("inventory_reserve", {"sku": "MUG-1", "qty": 2}),
                responses,
            )
        except BaseException as exc:  # noqa: BLE001 - the transport raises a task-group error
            caught = exc
        else:
            caught = None
        reserved = await in_session(
            asgi,
            "tok-readwrite-valid",
            lambda s: s.call_tool("inventory_reserve", {"sku": "MUG-1", "qty": 1}),
        )
        return caught, reserved

    caught, reserved = serve(build(), steps)
    assert caught is not None and any(isinstance(e, MCPError) for e in leaves(caught))
    denied = [r for r in responses if r.status_code == 403]
    assert len(denied) == 1
    challenge = params(denied[0].headers["www-authenticate"])
    assert challenge["error"] == "insufficient_scope"
    assert challenge["scope"] == "shop:write"
    assert challenge["resource_metadata"] == METADATA_URL
    assert json.loads(reserved.content[0].text) == {"sku": "MUG-1", "qty": 1, "reserved": 1}


def test_tool_checks_the_write_scope_without_the_gate():
    server = build()
    asgi = mcpserver.app(server, gate=False)

    async def main():
        async with server.session_manager.run():
            return await in_session(
                asgi,
                "tok-read-valid",
                lambda s: s.call_tool("inventory_reserve", {"sku": "MUG-1", "qty": 1}),
            )

    result = anyio.run(main)
    assert result.is_error and "insufficient_scope" in result.content[0].text


@pytest.mark.parametrize("token", ["tok-wrong-audience", "tok-other-resource"])
def test_token_for_another_audience_is_rejected_with_401(token):
    response = raw_post(token)
    assert response.status_code == 401
    challenge = params(response.headers["www-authenticate"])
    assert challenge["error"] == "invalid_token"
    assert challenge["resource_metadata"] == METADATA_URL


def test_verifier_checks_audience_and_expiry_itself():
    verifier = mcpserver.FixtureTokenVerifier(TOKENS, resource=RESOURCE)

    async def check():
        return [
            await verifier.verify_token(t)
            for t in ("tok-read-valid", "tok-wrong-audience", "tok-expired", "nope")
        ]

    valid, wrong, expired, unknown = anyio.run(check)
    assert valid is not None and valid.scopes == ["shop:read"] and valid.resource == RESOURCE
    assert wrong is None and expired is None and unknown is None


def test_missing_token_gets_401_with_resource_metadata_and_scope():
    response = raw_post()
    assert response.status_code == 401
    challenge = params(response.headers["www-authenticate"])
    assert challenge["resource_metadata"] == METADATA_URL
    assert challenge["scope"] == "shop:read"


def test_expired_token_gets_401():
    assert raw_post("tok-expired").status_code == 401


def test_token_without_the_read_scope_gets_403():
    response = raw_post("tok-no-scopes")
    assert response.status_code == 403
    challenge = params(response.headers["www-authenticate"])
    assert challenge["error"] == "insufficient_scope" and challenge["scope"] == "shop:read"


@pytest.mark.parametrize("name", ["access_token", "token"])
def test_token_in_the_query_string_is_ignored(name):
    assert raw_post(url=f"{URL}?{name}=tok-readwrite-valid").status_code == 401


def test_protected_resource_metadata_document():
    async def steps(asgi):
        async with client(asgi) as http:
            root = await http.get(f"{BASE}/.well-known/oauth-protected-resource")
            pathed = await http.get(f"{BASE}/.well-known/oauth-protected-resource/mcp")
            return root, pathed

    root, pathed = serve(build(), steps)
    assert root.status_code == pathed.status_code == 200
    assert root.json() == pathed.json()
    document = ProtectedResourceMetadata.model_validate(root.json())
    assert str(document.resource) == RESOURCE
    assert [str(a) for a in document.authorization_servers] == [ISSUER]
    assert document.scopes_supported == ["shop:read", "shop:write"]
    assert document.bearer_methods_supported == ["header"]


def test_client_config_and_sdk_options():
    config = mcpserver.client_config(URL, "tok-read-valid")
    assert config == {
        "type": "http",
        "url": URL,
        "headers": {"Authorization": "Bearer tok-read-valid"},
    }
    options = mcpserver.sdk_options(URL, "tok-read-valid", allow=["mcp__shop__ticket_lookup"])
    assert options.mcp_servers == {"shop": config}
    assert options.strict_mcp_config is True
    assert options.allowed_tools == ["mcp__shop__ticket_lookup"]
    assert options.disallowed_tools == ["mcp__shop__inventory_reserve"]
    for allow in (["mcp__shop__*"], ["mcp__shop__inventory_reserve"]):
        with pytest.raises(ValueError):
            mcpserver.sdk_options(URL, "tok-read-valid", allow=allow)


def test_cli_parses_the_port(monkeypatch):
    seen = {}

    def fake_run(app, *, host, port):
        seen.update(host=host, port=port, app=app)

    monkeypatch.setattr("uvicorn.run", fake_run)
    code = mcpserver.main(
        ["--port", "8790", "--tokens", str(TOKENS), "--tickets", str(Path(TINYSHOP, "tickets"))]
    )
    assert code == 0 and seen["port"] == 8790 and seen["host"] == "127.0.0.1"


def test_scope_is_appended_even_when_the_description_mentions_scope():
    async def inner(scope, receive, send):
        header = b'Bearer error="invalid_token", error_description="needs scope=x"'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"www-authenticate", header)],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    gate = mcpserver.ScopeGate(inner, metadata_url=METADATA_URL)

    async def main():
        async with client(gate) as http:
            return await http.post(URL, json=LIST)

    response = anyio.run(main)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].endswith(', scope="shop:read"')
