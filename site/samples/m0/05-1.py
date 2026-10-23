import json
from pathlib import Path

from cost_lab.transport import make_client
from cost_lab_lessons import tool_loop
from pydantic import BaseModel

FIXTURES = Path("course/m0-cost-lab/fixtures")
MODEL = "claude-opus-5-5"
SKU_SCHEMA = {
    "type": "object",
    "properties": {"sku": {"type": "string", "description": "Catalogue id such as A1."}},
    "required": ["sku"],
    "additionalProperties": False,
}
TOOLS = [
    {
        "name": "get_price",
        "description": "Unit price in EUR for a SKU.",
        "strict": True,
        "input_schema": SKU_SCHEMA,
    },
    {
        "name": "get_stock",
        "description": "Units in stock for a SKU.",
        "strict": True,
        "input_schema": SKU_SCHEMA,
    },
]
CATALOGUE = {"A1": {"get_price": "12.50", "get_stock": "7"}}


def execute(name: str, tool_input: dict) -> str:
    return CATALOGUE[tool_input["sku"]][name]


class StockReport(BaseModel):
    sku: str
    price_eur: float
    in_stock: int
    reorder: bool


client, transport = make_client(FIXTURES, ["loop_turn1", "loop_turn2", "structured_ok"])
final_text, turns = tool_loop(
    client,
    model=MODEL,
    max_tokens=16000,
    system="Answer stock questions. Call every lookup you need in the same turn.",
    tools=TOOLS,
    messages=[{"role": "user", "content": "Price and stock of A1?"}],
    execute=execute,
)
print("loop:", turns, "turns,", repr(final_text))
second = transport.requests[1].body
print("tool results in one user message:", json.dumps(second["messages"][-1]))
print("strict tool on the wire:", json.dumps(second["tools"][0]))

report = client.messages.parse(
    model=MODEL,
    max_tokens=16000,
    output_format=StockReport,
    messages=[
        {
            "role": "user",
            "content": f"Turn this into a stock report: {final_text}. Reorder below 10 units.",
        }
    ],
)
print("output_config sent:", json.dumps(transport.requests[2].body["output_config"]))
print("parsed:", repr(report.parsed_output), "stop_reason:", report.stop_reason)
