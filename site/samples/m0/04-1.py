import json
from pathlib import Path

from cost_lab_lessons import batch_requests, join_batch

FIXTURES = Path("course/m0-cost-lab/fixtures")
MODEL = "claude-opus-5-5"
USD_PER_MTOK = {"input": 4.00, "output": 20.00}
BATCH_DISCOUNT = 0.5
ASSUMED_INPUT, ASSUMED_OUTPUT = 1200, 300

prompts = {str(n): f"Summarise changelog entry {n} in two sentences." for n in range(1, 7)}
requests = batch_requests(prompts, model=MODEL, max_tokens=16000)
print("first request:", json.dumps(requests[0]))

lines = (FIXTURES / "batch_results.jsonl").read_text().splitlines()
outcomes = join_batch(list(prompts), [json.loads(line) for line in lines])
for key, outcome in outcomes.items():
    print(f"item {key}: {outcome.kind:<9} retryable={outcome.retryable} text={outcome.text!r}")

billed = [key for key, o in outcomes.items() if o.kind == "succeeded"]
per_request = (
    ASSUMED_INPUT * USD_PER_MTOK["input"] + ASSUMED_OUTPUT * USD_PER_MTOK["output"]
) / 1e6
standard = len(billed) * per_request
batched = standard * BATCH_DISCOUNT
print(f"billed {len(billed)} of {len(prompts)}: standard ${standard:.4f}, batch ${batched:.4f}")
print("resubmit:", [key for key, o in outcomes.items() if o.retryable])
