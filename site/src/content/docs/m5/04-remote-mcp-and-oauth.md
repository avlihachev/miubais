---
title: Remote MCP and OAuth
description: A remote MCP server over Streamable HTTP with the Python mcp 2.3.0 SDK, Protected Resource Metadata, the exact 401 and 403 challenges, audience binding and why token passthrough is forbidden, the confused deputy and discovery SSRF, and how the Agent SDK connects to such a server and reports needs-auth.
module: m5
order: 4
verified_on: 2026-10-17
executed: local
pins:
  "pypi:claude-agent-sdk": "0.2.168"
  "pypi:mcp": "2.3.0"
  "model:default": claude-opus-5-5
sources:
  - url: https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization
    title: "MCP specification 2026-07-28: Authorization"
    checked: 2026-10-17
  - url: https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices
    title: MCP Security Best Practices
    checked: 2026-10-17
  - url: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports
    title: "MCP specification 2026-07-28: Transports"
    checked: 2026-10-17
  - url: https://py.sdk.modelcontextprotocol.io/v2/migration/
    title: MCP Python SDK v2 migration guide
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/agent-sdk/mcp
    title: Connect to external tools with MCP
    checked: 2026-10-17
  - url: https://code.claude.com/docs/en/security
    title: Claude Code security
    checked: 2026-10-17
---

**Prerequisites:** [lesson 03](../03-permissions-sandboxing-and-secrets/), which explains why MCP servers run outside the Bash sandbox and need their own boundary.

## Why this matters for the factory

A factory agent also talks to services that are not files on disk: the ticket tracker, the inventory system, the deploy API. MCP is how those services show up as tools, and a remote MCP server is a network service that accepts requests carrying a token. Two things go wrong. The server accepts a token that was never meant for it, so a token leaked from one service opens another (ASI03, identity and privilege abuse). Or the agent holds a token with more scopes than the ticket needs, so an injected instruction can call a write tool that should never have been reachable (ASI02).

Claude Code's security page is blunt about who is responsible: Anthropic reviews connectors for its directory "but does not security-audit or manage any MCP server." If you run the server, its authorization is yours. Stage 04 of the exercise builds one: a `shop` server with a read tool and a write tool, served over Streamable HTTP, that checks bearer tokens, audience and scopes, and answers with the challenges the MCP authorization specification defines.

## Core idea

The MCP server is an OAuth 2.1 resource server. It never issues tokens; an authorization server does. Its job is to answer three questions on every request, in this order:

1. **Is there a token, in the right place?** Only the `Authorization: Bearer` header counts. No token, or a token in the query string, gets 401 with a pointer to the server's metadata.
2. **Was this token issued for me?** The token's audience must be this server's canonical URI. A token for another resource is invalid here, whatever scopes it carries: 401.
3. **Does it carry the scope this operation needs?** A valid token without the scope gets 403 `insufficient_scope` and a `scope` challenge naming exactly what is missing, so the client can step up.

The second question is easy to skip, because a token with the right scopes looks right. Scopes say what a token may do; audience says where. Checking only scopes means any service that can obtain a token from the same authorization server can spend it at yours.

## Mechanics

### Streamable HTTP and the Python SDK

In protocol revision 2026-07-28 the standard transports are stdio and Streamable HTTP, where "each message is an HTTP POST to a single MCP endpoint; replies arrive as a JSON object or a request-scoped SSE stream." The specification says authorization applies to HTTP: "Implementations using an STDIO transport SHOULD NOT follow this specification, and instead retrieve credentials from the environment."

The Python SDK 2.x renamed its high-level server: "The `FastMCP` class has been renamed to `MCPServer`", imported from `mcp.server.mcpserver` (MCP Python SDK v2 migration guide). The exercise builds `MCPServer(name="shop", token_verifier=..., auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=["shop:read"]))`, registers `ticket_lookup` and `inventory_reserve` as tools, and mounts `server.streamable_http_app(json_response=True)` in a Starlette app at `/mcp`. The migration guide's warning applies: the host app's lifespan must enter `server.session_manager.run()`, or requests fail with `RuntimeError: Task group is not initialized.` The tests drive the app in-process with `httpx2.ASGITransport` and the SDK's own client, `streamable_http_client` plus `ClientSession`, so nothing listens on a port; `python -m injection_lab.mcpserver --port 8790` serves it for the live stage.

### Protected Resource Metadata

"MCP servers MUST implement OAuth 2.0 Protected Resource Metadata (RFC9728). MCP clients MUST use OAuth 2.0 Protected Resource Metadata for authorization server discovery." The exercise serves the document at `/.well-known/oauth-protected-resource` and at the path-inserted form `/.well-known/oauth-protected-resource/mcp`, with `resource` (the canonical URI `https://shop.example.invalid/mcp`), `authorization_servers`, `scopes_supported: [shop:read, shop:write]` and `bearer_methods_supported: [header]`. A client that gets a 401 reads the `resource_metadata` URL from the challenge, fetches this document, finds the authorization server and starts the flow.

The specification asks for the canonical URI without a trailing slash and recommends that `scopes_supported` be "the minimal set of scopes necessary for basic functionality", with more requested later. Publishing every scope you have is listed under common mistakes in the security best practices.

### The challenges, header by header

The specification's example 401 is:

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource",
                         scope="files:read"
```

and its insufficient-scope example is:

```
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_scope",
                         scope="files:write",
                         resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource",
                         error_description="File write permission required for this operation"
```

The rules behind them: tokens go in `Authorization: Bearer <access-token>`, "authorization MUST be included in every HTTP request from client to server", and "Access tokens MUST NOT be included in the URI query string". "Invalid or expired tokens MUST receive a HTTP 401 response." For scope, the server "SHOULD include all scopes required for the current operation in a single challenge" rather than one at a time. The sample walks a table of requests through the lesson's small checker, which applies the three questions in order with an invented token table and a fixed clock.

Sample: `site/samples/m5/04-1.py`.

```python
from datetime import UTC, datetime

from injection_lab_lessons import TokenRow, check_request

RESOURCE = "https://shop.example.invalid/mcp"
METADATA = "https://shop.example.invalid/.well-known/oauth-protected-resource/mcp"
NOW = datetime(2026, 10, 17, tzinfo=UTC)
LATER = datetime(2099, 1, 1, tzinfo=UTC)
table = {
    "demo-read": TokenRow(RESOURCE, ("shop:read",), LATER),
    "demo-write": TokenRow(RESOURCE, ("shop:read", "shop:write"), LATER),
    "demo-other-aud": TokenRow(
        "https://crm.example.invalid/mcp", ("shop:read", "shop:write"), LATER
    ),
    "demo-expired": TokenRow(RESOURCE, ("shop:read", "shop:write"), NOW.replace(year=2020)),
}
cases = [
    ("no token", {}, {}, "shop:read"),
    ("token in query", {}, {"access_token": "demo-write"}, "shop:read"),
    ("read token, read", {"Authorization": "Bearer demo-read"}, {}, "shop:read"),
    ("read token, write", {"Authorization": "Bearer demo-read"}, {}, "shop:write"),
    ("other audience", {"Authorization": "Bearer demo-other-aud"}, {}, "shop:write"),
    ("expired", {"Authorization": "Bearer demo-expired"}, {}, "shop:read"),
    ("write token, write", {"Authorization": "Bearer demo-write"}, {}, "shop:write"),
]
for name, headers, query, needed in cases:
    outcome = check_request(
        headers,
        query,
        table=table,
        resource=RESOURCE,
        needed=needed,
        now=NOW,
        metadata_url=METADATA,
    )
    print(f"{name:<19} {outcome.replace(METADATA, '<metadata>')}")
```

Output, run on 2026-10-17:

```
no token            401 Bearer resource_metadata="<metadata>", scope="shop:read"
token in query      401 Bearer resource_metadata="<metadata>", scope="shop:read"
read token, read    200 OK
read token, write   403 Bearer error="insufficient_scope", resource_metadata="<metadata>", scope="shop:write"
other audience      401 Bearer error="invalid_token", resource_metadata="<metadata>", scope="shop:write"
expired             401 Bearer error="invalid_token", resource_metadata="<metadata>", scope="shop:read"
write token, write  200 OK
```

The query-string token is a valid write token, and it gets exactly the answer a missing token gets. `demo-other-aud` carries both scopes, and it gets 401 `invalid_token`, not 403: the server does not discuss scopes with a token that was never meant for it. The read token gets 200 for a read and 403 with `scope="shop:write"` for a write, which is the step-up signal. In the exercise, the write check happens twice: a gate in front of the MCP app parses `tools/call` and answers 403 before `inventory_reserve` runs, and the tool checks the scope again itself, so the test that turns the gate off still sees a tool error rather than a reservation.

### Audience binding and token passthrough

The token handling section is short and absolute. Servers "MUST validate that access tokens were issued specifically for them as the intended audience"; they "MUST only accept tokens that are valid for use with their own resources"; and "MCP servers MUST NOT accept or transit any other tokens." On the client side, the `resource` parameter (RFC 8707) "MUST be included in both authorization requests and token requests" and must name the MCP server, which is what puts the audience into the token in the first place.

The security best practices name the failure: "Token passthrough" is "an anti-pattern where an MCP server accepts tokens from an MCP client without validating that the tokens were properly issued *to the MCP server* and passes them through to the downstream API", and it "is explicitly forbidden in the authorization specification". Among the listed risks: the server cannot tell clients apart, downstream logs show the wrong identity, and "a malicious actor in possession of a stolen token can use the server as a proxy for data exfiltration." The mitigation is one line: "MCP servers MUST NOT accept any tokens that were not explicitly issued for the MCP server." If your server calls another API, it gets its own token for that API.

The exercise's `FixtureTokenVerifier` checks opaque tokens against `tests/TOKENS.yaml` (audience, scopes, expiry). That is a teaching stand-in: a real deployment validates a JWT's signature, issuer, audience and expiry against the authorization server's keys, or introspects the token. The checks and the status codes are the same.

### Confused deputy and discovery SSRF

The best practices describe two more attacks. The confused deputy applies to MCP servers that proxy a third-party API with a static client id: an attacker registers a client dynamically, sends the user a crafted link, the third party's consent cookie skips the consent screen, and the authorization code lands at the attacker's redirect URI. The fix is per-client consent at the MCP server before forwarding, exact redirect URI matching and a `state` value set only after consent. Server-side request forgery hits clients during discovery: a malicious server can put `http://169.254.169.254/` or a private address in `resource_metadata` or in its metadata document, so clients deployed on servers should require HTTPS, block private and link-local ranges and route discovery through an egress proxy.

### The Agent SDK side

The client configuration is an `mcp_servers` entry: `{"type": "http", "url": "...", "headers": {"Authorization": "Bearer ..."}}`, with tools named `mcp__<server-name>__<tool-name>` (Connect to external tools with MCP). The guide's advice is "Prefer `allowedTools` over permission modes for MCP access", because a pattern grants exactly the tools you name. The exercise's `sdk_options` goes further for a factory: `strict_mcp_config=True` so only these servers load, `allowed_tools` listing the read tool, the write tool in `disallowed_tools`, and a `ValueError` if an allow pattern such as `mcp__shop__*` would match the write tool. Least privilege is enforced on both sides: the token lacks `shop:write` and the agent cannot see the tool.

On OAuth, the guide is explicit that the SDK will not do it for you: "The SDK doesn't open a browser or run an interactive OAuth flow. When a configured server returns an authorization challenge and no stored token is available, the agent run continues without that server's tools, and the server reports status `needs-auth`." Because the run continues, a factory harness should read the init message or `get_mcp_status()` and stop when a required server is `needs-auth` or `failed`, rather than let the agent fall back to other tools.

## Common pitfalls

- **Checking scopes, not audience.** The right scopes on a token for another service still mean "not for you". Reject with 401.
- **Forwarding the client's token downstream.** That is token passthrough. Get your own token for the downstream API.
- **Accepting `?access_token=`.** Tokens in URLs end up in logs and referrers. Only the header counts.
- **Answering a missing scope with 401.** The client then re-authenticates instead of stepping up. Use 403 `insufficient_scope` with the scope it needs, all of it in one challenge.
- **A wildcard allow for an MCP server with write tools.** `mcp__shop__*` grants the writes too. List read tools and deny writes by name.
- **Ignoring `needs-auth`.** The run continues without the server's tools; check the status and fail the run.

## What interviewers ask

**What should an MCP server check on every request?**
That a bearer token is in the `Authorization` header (never the query string), that it is valid, unexpired and issued for this server as its audience, and that it carries the scope the operation needs. Missing or invalid tokens get 401 with a `resource_metadata` pointer; a valid token lacking a scope gets 403 `insufficient_scope` with the required scope.

**Why is audience validation separate from scope validation?**
Scopes describe what a token may do; audience describes which resource it is for. Without the audience check, any token from the same authorization server with matching scope names works at your server, so a leak anywhere becomes access here. The MCP specification requires servers to validate audience and forbids accepting or transiting other tokens.

**What is token passthrough and why is it forbidden?**
An MCP server accepting a client's token without checking it was issued for the server, and forwarding it to a downstream API. It bypasses downstream controls that depend on audience, breaks the audit trail, and turns the server into an exfiltration proxy for a stolen token. The server must use its own token for downstream calls.

**How does an Agent SDK agent authenticate to a remote MCP server?**
Your application completes OAuth and passes the access token in the server's `headers`; the SDK does not run an interactive flow, and a server that challenges without a stored token shows `needs-auth` while the run continues without its tools. Pair it with `strict_mcp_config`, an `allowed_tools` list of specific tools and the write tools in `disallowed_tools`.

## Sources

- [MCP specification 2026-07-28: Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization), sections Protocol Requirements, Scope Selection Strategy, Resource Parameter Implementation, Access Token Usage, Error Handling, checked 2026-10-17
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices), sections Confused Deputy Problem, Token Passthrough, Server-Side Request Forgery, Scope Minimization, checked 2026-10-17
- [MCP specification 2026-07-28: Transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports), checked 2026-10-17
- [MCP Python SDK v2 migration guide](https://py.sdk.modelcontextprotocol.io/v2/migration/), checked 2026-10-17
- [Connect to external tools with MCP](https://code.claude.com/docs/en/agent-sdk/mcp), sections Allow MCP tools, Authentication, Error handling, Claude Agent SDK docs, checked 2026-10-17
- [Claude Code security](https://code.claude.com/docs/en/security), section MCP security, checked 2026-10-17
- Course code (repository files, not web sources): stage 04 in `course/m5-injection-lab/README.md` and `tests/test_04_remote_mcp.py`, `tests/TOKENS.yaml`, the lesson helpers in `course/m5-injection-lab/lesson_support/src/injection_lab_lessons/`
