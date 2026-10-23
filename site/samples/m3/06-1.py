from pathlib import Path

from harnesskit.testing import load_run
from trace_lab_lessons import parallel_turns, span_tree, tool_durations, tool_latency_table

spans, parallel, tool_turns, chat_ms, wall_ms = [], 0, 0, 0, 0
for path in sorted(Path("fixtures/harness-runs/runs").glob("r*.jsonl")):
    timed = load_run(path)
    spans += tool_durations(timed)
    counts = parallel_turns(timed)
    parallel, tool_turns = parallel + counts[0], tool_turns + counts[1]
    nodes = span_tree(timed)
    wall_ms += nodes[0].duration_ms
    chat_ms += sum(n.duration_ms for n in nodes if n.name.startswith("chat "))

print("tool span durations, ms, over 40 recorded runs")
print(tool_latency_table(spans))
print(f"turns with parallel tool calls: {parallel} of {tool_turns}")
print(f"share of wall time in chat spans: {chat_ms / wall_ms:.1%}")
