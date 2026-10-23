from capstone_lessons import WEIGHTS, Signals, rank_prs

existing = (1, 2, 3, 4, 5, 6)
prs = [
    Signals("a-docs", touches=("docs/runbook.md",), approvals=1, age_days=2),
    Signals(
        "b-schema",
        touches=("migrations/0007_glossaries.sql",),
        approvals=1,
        age_days=1,
        existing_migrations=existing,
        new_migrations=(7,),
    ),
    Signals(
        "c-dup-migration",
        touches=("migrations/0006_due_at.sql",),
        approvals=2,
        age_days=3,
        existing_migrations=existing,
        new_migrations=(6,),
    ),
    Signals(
        "d-red-tests",
        touches=("internal/api/routes.go",),
        approvals=1,
        age_days=1,
        tests_failed=True,
    ),
    Signals("e-stale", touches=("internal/store/cache.go",), approvals=0, age_days=21),
    Signals(
        "f-rebase",
        touches=("proto/glossaries/v1/glossaries.proto",),
        approvals=1,
        age_days=5,
        applied=False,
    ),
    Signals(
        "g-ui-major",
        touches=("web/src/cart.ts",),
        approvals=1,
        age_days=1,
        finding_severities=("major", "minor"),
    ),
]

print("weights:", ", ".join(f"{kind} {weight}" for kind, weight in WEIGHTS.items()))
print(f"{'pr':<17}{'score':>5}  {'verdict':<8}blockers")
for row in rank_prs(prs):
    print(f"{row.pr:<17}{row.score:>5}  {row.verdict:<8}{', '.join(row.kinds) or 'none'}")
