from collections import Counter

from harnesskit.testing import load_run
from trace_lab_lessons import render_tree, span_tree

timed = load_run("fixtures/harness-runs/runs/r018.jsonl")
kinds = Counter(type(item.message).__name__ for item in timed)
print("messages:", dict(sorted(kinds.items())))

nodes = span_tree(timed)
print(render_tree(nodes))
print("spans:", len(nodes), "chat:", sum(n.name.startswith("chat") for n in nodes))
