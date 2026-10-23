import json
from pathlib import Path

from cost_lab.transport import make_client

client, transport = make_client(Path("course/m0-cost-lab/fixtures"), ["stream_ok"])
with client.beta.messages.stream(
    model="claude-opus-5-5",
    max_tokens=64000,
    betas=["task-budgets-2026-03-13"],
    output_config={"effort": "low", "task_budget": {"type": "tokens", "total": 40000}},
    messages=[
        {
            "role": "user",
            "content": "Triage the failing test in tests/test_api.py and propose a fix.",
        }
    ],
) as stream:
    final = stream.get_final_message()

sent = transport.requests[0].body
print("sent:", json.dumps({k: sent[k] for k in ("model", "max_tokens", "output_config", "stream")}))
print(
    "stop_reason:", final.stop_reason, "usage:", final.usage.input_tokens, final.usage.output_tokens
)
