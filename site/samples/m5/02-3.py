from pathlib import Path

from injection_lab_lessons import live_summary

live = live_summary(Path("course/m5-injection-lab/fixtures/live_injection_run.json"))
print(f"model {live['model']}, caps {live['max_turns']} turns / {live['limit_usd']} USD")
first = live["first_attempt"]
print(
    f"attempt 1: {first['turns']} turns, {first['cost_usd']} USD, taint events {first['taint_events']}"
)
print(f"attempt 2: planted in {live['planted_in']} files, stopped by {live['stopped_by']}")
print(f"  turns {live['turns']}, cost {live['cost_usd']} USD, taint events {live['taint_events']}")
print(
    f"  denied {live['denied']} ({live['denied_by_taint']} by the taint), curl attempts {live['curl_attempts']}"
)
print(f"  files changed {live['files_changed']}, checklist {live['checklist']}")
