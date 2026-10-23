from pathlib import Path

from capstone_lessons import accept_findings, changed_paths, live_summary

patch = """\
--- a/internal/api/routes.go
+++ b/internal/api/routes.go
@@ -10,3 +10,4 @@
--- a/web/src/legacy.ts
+++ /dev/null
@@ -1,2 +0,0 @@
"""
print("changed:", ", ".join(changed_paths(patch)))

keys = ("file", "line", "severity", "category", "message", "confidence")
rows = [
    ("internal/api/routes.go", 12, "major", "input-unvalidated", "limit reaches the store", 0.8),
    ("internal/api/routes.go", 0, "major", "input-unvalidated", "line zero cannot be cited", 0.7),
    ("web/src/legacy.ts", 1, "critical", "test-removed", "the only formatting test is gone", 0.9),
    ("internal/api/routes.go", 14, "minor", "naming", "the handler name says nothing", 0.5),
]
raw = [dict(zip(keys, row, strict=True)) for row in rows]
accepted, rejected = accept_findings(raw)
print(f"accepted {len(accepted)} of {len(raw)}")
for reason in rejected:
    print(" ", reason)

live = live_summary(Path("course/m7-capstone/fixtures/live_review_run.json"))
print(f"live run on {live['model']}: {live['reviewed']} of {live['prs']} PRs reviewed")
print(
    f"cost per reviewed PR, USD: min {live['usd_min']:.4f}"
    f"  median {live['usd_median']:.4f}  max {live['usd_max']:.4f}"
)
print(f"turns: median {live['turns_median']}  max {live['turns_max']}")
print(f"seconds per PR, tests and review: median {live['seconds_median']:.1f}")
