from evals_lab_lessons import gate_check

baseline = {
    "pass_rate": 0.445,
    "counts": {"success": 64, "loop": 18, "silent-skip": 17, "context-loss": 21},
}
runs = {
    "steady": {
        "pass_rate": 0.44,
        "counts": {"success": 63, "loop": 19, "silent-skip": 17, "context-loss": 21},
    },
    "drop": {
        "pass_rate": 0.42,
        "counts": {"success": 62, "loop": 19, "silent-skip": 18, "context-loss": 21},
    },
    "loop spike": {
        "pass_rate": 0.44,
        "counts": {"success": 62, "loop": 22, "silent-skip": 16, "context-loss": 20},
    },
    "exactly 2 points": {
        "pass_rate": 0.425,
        "counts": {"success": 62, "loop": 19, "silent-skip": 18, "context-loss": 21},
    },
}
for name, run in runs.items():
    verdict = gate_check(run, baseline)
    print(f"{name:<17} {'gate ok' if verdict.ok else 'gate failed'}")
    for reason in verdict.reasons:
        print(f"  {reason}")

base, last = baseline["pass_rate"], runs["exactly 2 points"]["pass_rate"]
print()
print(f"float drop:            {base - last!r}")
print(f"float drop > 0.02:     {base - last > 0.02}")
print(f"ten-thousandths drop:  {round(base * 10_000) - round(last * 10_000)} (limit 200)")
