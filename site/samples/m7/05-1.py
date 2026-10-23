from pathlib import Path

from capstone_lessons import live_summary

live = live_summary(Path("course/m7-capstone/fixtures/live_review_run.json"))
verdicts = live["verdicts"]
rows = [
    ("PRs / reviewed by the agent", f"{live['prs']} / {live['reviewed']}"),
    ("total cost, USD", f"{live['total_usd']:.2f}"),
    ("mean cost per reviewed PR, USD", f"{live['usd_mean']:.3f}"),
    ("cost per 100 such PRs, USD", f"{100 * live['usd_mean']:.2f}"),
    ("wall time, s (sequential)", f"{live['wall_seconds']:.0f}"),
    ("median time per PR, s", f"{live['seconds_median']:.1f}"),
    ("merge / hold / block", f"{verdicts['merge']} / {verdicts['hold']} / {verdicts['block']}"),
    ("verdicts equal to the key", f"{live['agree_with_key']} of {live['prs']}"),
    ("findings after cleaning", f"{live['findings']}"),
    ("of them matching no label", f"{live['noise']}"),
    ("precision / recall", f"{live['precision']:.3f} / {live['recall']:.3f}"),
    ("blocker recall", f"{live['blocker_recall']:.2f}"),
    ("failed reviews", f"{live['review_failed']}"),
]
for label, value in rows:
    print(f"{label:<32}{value:>12}")
