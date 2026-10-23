from trace_lab_lessons import LessonRouter, Outcome, Route

routes = [
    Route("cheap", "claude-haiku-5-5", 0.05, 8),
    Route("default", "claude-sonnet-5-5", 0.40, 15),
    Route("strong", "claude-opus-5-5", 1.00, 25),
]

scripted = {
    ("readme-typo", "claude-haiku-5-5"): Outcome("success", 0.004, 3),
    ("flaky-test", "claude-haiku-5-5"): Outcome("max_turns", 0.012, 8),
    ("flaky-test", "claude-sonnet-5-5"): Outcome("budget", 0.402, 11),
    ("flaky-test", "claude-opus-5-5"): Outcome("success", 0.310, 6),
    ("drop-table", "claude-haiku-5-5"): Outcome("policy", 0.002, 2),
}


def fake_run(ticket_id, *, model, max_turns, max_budget_usd):
    return scripted[(ticket_id, model)]


router = LessonRouter(routes)
for ticket in ("readme-typo", "flaky-test", "drop-table"):
    final, attempts = router.run(ticket, fake_run)
    steps = " -> ".join(f"{name}:{outcome.stopped_by}" for name, outcome in attempts)
    spent = sum(outcome.cost_usd for _, outcome in attempts)
    print(f"{ticket:<12} {steps:<50} ends on {final:<7} {spent:.3f} USD")

print()
print(router.table())
