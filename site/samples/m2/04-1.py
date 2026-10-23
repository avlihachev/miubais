from evals_lab_lessons import suite_pass_at_k, suite_pass_hat_k

P, F = True, False
runs = {
    "fix-rounding": [P, P, P, P, P],
    "add-endpoint": [P, P, P, P, P],
    "rename-flag": [P, P, F, P, P],
    "null-guard": [P, F, P, P, P],
    "retry-on-429": [F, P, P, F, P],
    "migrate-config": [P, F, F, P, F],
    "flaky-cache": [F, F, P, F, F],
    "cross-repo-bump": [F, F, F, F, F],
}
for task, results in runs.items():
    print(f"{task:<16} {''.join('P' if r else '.' for r in results)}  {sum(results)}/5")
print()
print(f"{'k':>2} {'pass@k':>7} {'pass^k':>7}")
for k in (1, 3, 5):
    print(f"{k:>2} {suite_pass_at_k(runs, k):>7.4f} {suite_pass_hat_k(runs, k):>7.4f}")
