from datetime import UTC, datetime
from pathlib import Path

from cost_lab.transport import make_client
from cost_lab_lessons import cache_counters, cached_request, prefix_fingerprint

FIXTURES = Path("course/m0-cost-lab/fixtures")
MODEL = "claude-opus-5-5"
USD_PER_MTOK = {"input": 4.00, "cache_write_5m": 5.00, "cache_read": 0.20, "output": 20.00}
SYSTEM = "\n".join(
    f"Rule {i}: quote prices in EUR with two decimals and cite the catalogue row for part family {i}."
    for i in range(1, 121)
)
TOOLS = [
    {
        "name": "get_stock",
        "description": "Units in stock for a part id.",
        "input_schema": {
            "type": "object",
            "properties": {"part": {"type": "string"}},
            "required": ["part"],
        },
    },
    {
        "name": "get_price",
        "description": "Unit price in EUR for a part id.",
        "input_schema": {
            "type": "object",
            "properties": {"part": {"type": "string"}},
            "required": ["part"],
        },
    },
]


def cost_usd(usage) -> float:
    return (
        usage.input_tokens * USD_PER_MTOK["input"]
        + (usage.cache_creation_input_tokens or 0) * USD_PER_MTOK["cache_write_5m"]
        + (usage.cache_read_input_tokens or 0) * USD_PER_MTOK["cache_read"]
        + usage.output_tokens * USD_PER_MTOK["output"]
    ) / 1_000_000


def request(history: list[dict], user_turn: str, tools: list[dict], system: str = SYSTEM) -> dict:
    return cached_request(
        model=MODEL,
        max_tokens=16000,
        system=system,
        tools=tools,
        history=history,
        user_turn=user_turn,
    )


client, transport = make_client(FIXTURES, ["cache_write", "cache_read"])
history: list[dict] = []
for turn, tools in [("Price of A1?", TOOLS), ("And how many are in stock?", list(reversed(TOOLS)))]:
    response = client.messages.create(**request(history, turn, tools))
    r = cache_counters(response.usage)
    print(
        f"total={r.total} written={r.written} read={r.read} uncached={r.uncached} "
        f"hit_ratio={r.hit_ratio:.2f} cost=${cost_usd(response.usage):.6f}"
    )
    history += [
        {"role": "user", "content": turn},
        {"role": "assistant", "content": response.content},
    ]

sent = [prefix_fingerprint(req.body) for req in transport.requests]
print("prefix identical across turns, tool order shuffled:", sent[0] == sent[1])

stamped = request(history, "Next?", TOOLS, system=f"Now: {datetime.now(UTC).isoformat()}\n{SYSTEM}")
print("prefix identical with a timestamp in system:", prefix_fingerprint(stamped) == sent[0])

operator_note = request(history, "Next?", TOOLS)
operator_note["messages"].append(
    {"role": "system", "content": "Prices for family 7 changed at 14:00 UTC."}
)
print(
    "mid-conversation system message leaves the prefix unedited:",
    prefix_fingerprint(operator_note) == sent[0],
)
