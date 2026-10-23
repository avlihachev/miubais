from capstone.types import Finding, Label
from capstone_lessons import pair_up, same_file, same_issue, score

labels = [
    Label(file="billing/charge.go", start=40, end=44, category="error-swallowed", severity="major"),
    Label(file="billing/keys.go", start=7, end=7, category="secret-in-code", severity="blocker"),
    Label(file="ui/cart.ts", start=12, end=12, category="ts-any", severity="minor"),
]


def finding(file, line, category, severity, confidence):
    return Finding(
        file=file,
        line=line,
        severity=severity,
        category=category,
        message=f"{category} near line {line}",
        confidence=confidence,
    )


findings = [
    finding("billing/charge.go", 46, "error-swallowed", "major", 0.9),
    finding("billing/charge.go", 41, "error-swallowed", "major", 0.6),
    finding("billing/charge.go", 90, "style", "minor", 0.7),
    finding("billing/keys.go", 7, "secret-in-code", "blocker", 0.95),
    finding("ui/cart.ts", 30, "ts-any", "minor", 0.8),
]

for name, rule in (("file, line window, category", same_issue), ("file only", same_file)):
    pairs = pair_up(findings, labels, rule)
    overall = score(findings, labels, pairs)
    blocker = score(findings, labels, pairs, "blocker")
    print(f"rule: {name}")
    for i, j in pairs:
        f, label = findings[i], labels[j]
        print(f"  {f.file}:{f.line} {f.category} -> label {label.start}-{label.end}")
    print(
        f"  precision {overall.precision:.2f} ({len(pairs)}/{overall.findings})"
        f"  recall {overall.recall:.2f} ({len(pairs)}/{overall.labels})"
        f"  blocker recall {blocker.recall:.2f}"
    )
