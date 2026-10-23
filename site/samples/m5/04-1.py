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
