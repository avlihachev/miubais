from evals_lab_lessons import Finding, review_scores, review_table

labels = [
    Finding("pr-101", "internal/billing/charge.go", 88, "blocker"),
    Finding("pr-101", "internal/billing/charge.go", 140, "minor"),
    Finding("pr-102", "web/src/cart/total.ts", 31, "blocker"),
    Finding("pr-102", "web/src/cart/total.ts", 77, "major"),
    Finding("pr-103", "cmd/worker/main.go", 12, "major"),
    Finding("pr-103", "internal/queue/retry.go", 54, "blocker"),
    Finding("pr-103", "internal/queue/retry.go", 99, "minor"),
    Finding("pr-104", "web/src/auth/session.ts", 20, "major"),
]
reported = [
    Finding("pr-101", "internal/billing/charge.go", 90, "blocker"),
    Finding("pr-101", "internal/billing/charge.go", 200, "minor"),
    Finding("pr-102", "web/src/cart/total.ts", 31, "blocker"),
    Finding("pr-102", "web/src/cart/total.ts", 33, "blocker"),
    Finding("pr-102", "web/src/cart/total.ts", 76, "minor"),
    Finding("pr-103", "internal/queue/retry.go", 61, "blocker"),
    Finding("pr-103", "cmd/worker/main.go", 12, "major"),
    Finding("pr-104", "web/src/auth/session.ts", 5, "minor"),
    Finding("pr-104", "web/src/api/client.ts", 44, "minor"),
]
print(review_table(review_scores(reported, labels, tolerance=3)))
