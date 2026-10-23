from pathlib import Path

from harnesskit.testing import load_run
from trace_lab_lessons import cost_summary, load_prices, run_cost

prices = load_prices("fixtures/harness-runs/prices.json")
paths = sorted(Path("fixtures/harness-runs/runs").glob("r*.jsonl"))
runs = [run_cost(load_run(path), prices) for path in paths]
summary = cost_summary(runs)

wrong = {model: dict(p) for model, p in prices.items() if isinstance(p, dict)}
for price in wrong.values():
    price["cache_read"] = price["input"]
mispriced = sum(run_cost(load_run(path), wrong).usd for path in paths)

rows = [
    ("runs / tickets", f"{summary['runs']} / {summary['tickets']}"),
    ("total cost, USD", f"{summary['total_usd']:.4f}"),
    ("mean cache-hit ratio", f"{summary['mean_ticket_cache_hit']:.3f}"),
    ("costliest quartile share", f"{summary['top_quartile_run_share']:.1%}"),
    ("runs with a result", f"{summary['runs_with_result']}"),
    ("max |delta| below 1e-9", f"{summary['max_reconcile_delta'] < 1e-9}"),
    ("cache read as input, USD", f"{mispriced:.4f}"),
]
for label, value in rows:
    print(f"{label:<26}{value:>8}")
