import json
from pathlib import Path

from serving_lab_lessons.capacity import usd_per_mtok_out

run = json.loads(Path("course/m6-serving-lab/fixtures/benchmarks/sample-run.json").read_text())
summary = run["summary"]
tokens = round(summary["throughput_tps"] * summary["wall_s"])
print(f"synthetic={run['synthetic']}: {tokens} output tokens in {summary['wall_s']} s")

for usd_per_hour in (1.49, 2.99, 3.99, 6.88):
    busy = usd_per_mtok_out(usd_per_hour, summary["wall_s"], tokens)
    quarter = usd_per_mtok_out(usd_per_hour, 4 * summary["wall_s"], tokens)
    print(f"{usd_per_hour:5.2f} USD/h: {busy:5.2f} USD/Mtok busy, {quarter:5.2f} at 25% busy")

one_stream = usd_per_mtok_out(2.99, 3600, round(summary["p50_tps"] * 3600))
print(f"one stream at a time, 2.99 USD/h: {one_stream:.2f} USD/Mtok")
