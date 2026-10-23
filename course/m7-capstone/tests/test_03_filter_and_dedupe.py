import pytest
from capstone import filter as hygiene
from capstone.review import FakeReviewer, changed_files
from capstone.types import Finding, VerifyResult

CLEAN_COUNTS = {
    "pr-01": 1,
    "pr-02": 1,
    "pr-03": 2,
    "pr-04": 2,
    "pr-05": 1,
    "pr-06": 2,
    "pr-07": 2,
    "pr-08": 2,
    "pr-09": 1,
    "pr-10": 0,
    "pr-11": 1,
    "pr-12": 1,
}


def finding(file="a.go", line=10, category="error-swallowed", confidence=0.8, severity="major"):
    return Finding(
        file=file,
        line=line,
        severity=severity,
        category=category,
        message=f"{category} at {file}:{line}",
        confidence=confidence,
    )


def verify(go_ok=True, ts_ok=True):
    return VerifyResult(go_ok=go_ok, ts_ok=ts_ok, output="", duration_ms=5)


@pytest.fixture
def reviewed(fake_review, prs, repo):
    reviewer = FakeReviewer(fake_review)
    return {
        pr.id: (reviewer.review(pr, repo, []), changed_files((pr.dir / "patch.diff").read_text()))
        for pr in prs
    }


def test_only_touched_drops_findings_on_files_the_patch_does_not_touch():
    kept = finding("a.go")
    assert hygiene.only_touched([kept, finding("b.go")], ["a.go", "c.go"]) == [kept]
    assert hygiene.only_touched([finding("src/a.go")], ["a.go"]) == []


def test_hallucinated_pre_existing_issues_are_dropped(reviewed):
    review, changed = reviewed["pr-09"]
    assert "internal/store/memory.go" in {f.file for f in review.findings}
    kept = hygiene.clean(review.findings, changed)
    assert "internal/store/memory.go" not in {f.file for f in kept}
    review, changed = reviewed["pr-04"]
    kept = hygiene.clean(review.findings, changed)
    assert "migrations/0004_index_status.sql" not in {f.file for f in kept}


def test_labels_never_name_untouched_files(labels, prs):
    for pr in prs:
        changed = changed_files((pr.dir / "patch.diff").read_text())
        assert {f["file"] for f in labels[pr.id]["findings"]} <= set(changed), pr.id


def test_dedupe_keeps_the_most_confident_of_one_issue():
    low, high = finding(line=10, confidence=0.7), finding(line=11, confidence=0.9)
    assert hygiene.dedupe([low, high]) == [high]
    same_line = finding(line=10, confidence=0.6)
    assert hygiene.dedupe([same_line, low]) == [low]


def test_dedupe_window_is_two_lines():
    base = finding(line=10, confidence=0.9)
    assert hygiene.dedupe([base, finding(line=12, confidence=0.5)]) == [base]
    assert hygiene.dedupe([finding(line=8, confidence=0.5), base]) == [base]
    far = finding(line=13, confidence=0.5)
    assert hygiene.dedupe([base, far]) == [base, far]
    below = finding(line=7, confidence=0.5)
    assert hygiene.dedupe([below, base]) == [below, base]


def test_dedupe_never_merges_different_categories_on_one_line():
    secret = finding("web/src/api.ts", 3, "secret-in-code", 0.97, "blocker")
    style = finding("web/src/api.ts", 3, "style", 0.7, "minor")
    assert hygiene.dedupe([secret, style]) == [secret, style]


def test_dedupe_never_merges_different_files():
    a, b = finding("a.go", 10), finding("b.go", 10)
    assert hygiene.dedupe([a, b]) == [a, b]


def test_dedupe_keeps_input_order():
    first = finding("z.go", 1, confidence=0.6)
    second = finding("a.go", 1, confidence=0.9)
    assert hygiene.dedupe([first, second]) == [first, second]


def test_threshold_keeps_findings_at_or_above_the_minimum():
    at, below, above = finding(confidence=0.6), finding(confidence=0.59), finding(confidence=0.95)
    assert hygiene.threshold([at, below, above]) == [at, above]
    assert hygiene.threshold([at, below, above], min_confidence=0.9) == [above]
    assert hygiene.threshold([at, below, above], min_confidence=0.0) == [at, below, above]


def test_clean_composes_the_three(reviewed):
    for pr_id, (review, changed) in reviewed.items():
        kept = hygiene.clean(review.findings, changed)
        assert len(kept) == CLEAN_COUNTS[pr_id], pr_id
        assert all(f.file in changed and f.confidence >= 0.6 for f in kept), pr_id
        assert hygiene.dedupe(kept) == kept
    assert sum(CLEAN_COUNTS.values()) == 16


def test_clean_keeps_the_most_confident_duplicate(reviewed):
    review, changed = reviewed["pr-02"]
    kept = hygiene.clean(review.findings, changed)
    assert [(f.line, f.confidence) for f in kept] == [(12, 0.95)]
    review, changed = reviewed["pr-05"]
    assert [f.confidence for f in hygiene.clean(review.findings, changed)] == [0.92]


def test_clean_respects_a_custom_threshold(reviewed):
    review, changed = reviewed["pr-06"]
    kept = hygiene.clean(review.findings, changed, min_confidence=0.5)
    assert {f.category for f in kept} == {
        "input-unvalidated",
        "error-swallowed",
        "changelog-missing",
    }


def test_clean_does_not_change_the_input(reviewed):
    review, changed = reviewed["pr-02"]
    before = list(review.findings)
    hygiene.clean(review.findings, changed)
    assert review.findings == before


def test_reconcile_overrides_a_tests_pass_claim_when_verify_failed():
    findings = [finding()]
    got = hygiene.reconcile(findings, "Small change. All tests pass.", verify(go_ok=False))
    assert got.findings == findings
    assert got.summary == "Small change. All tests pass."
    assert got.verify_note is not None
    assert "verify" in got.verify_note.lower() and "overrides" in got.verify_note.lower()
    assert "go test" in got.verify_note


def test_reconcile_names_the_failing_side():
    note = hygiene.reconcile([], "The tests pass with the new input.", verify(ts_ok=False))
    assert "node --test" in note.verify_note and "go test" not in note.verify_note


def test_reconcile_on_the_fake_reviews_of_failing_prs(reviewed):
    for pr_id, failed in (("pr-07", verify(ts_ok=False)), ("pr-09", verify(go_ok=False))):
        review, _ = reviewed[pr_id]
        assert hygiene.reconcile(review.findings, review.summary, failed).verify_note, pr_id


@pytest.mark.parametrize(
    "summary",
    ["No regressions, tests pass.", "Tests pass and there are no issues.", "CI is green."],
)
def test_a_negation_outside_the_claim_does_not_hide_it(summary):
    assert hygiene.reconcile([], summary, verify(go_ok=False)).verify_note is not None


@pytest.mark.parametrize(
    ("summary", "result"),
    [
        ("All tests pass.", verify()),
        ("All tests pass.", None),
        ("Adds a migration with an index.", verify(go_ok=False)),
        ("The tests do not pass on my reading.", verify(go_ok=False)),
        ("The tests do not pass.", verify(ts_ok=False)),
        ("No tests were run; the build never passed.", verify(go_ok=False)),
        ("No tests pass.", verify(go_ok=False)),
        ("No checks passed on the branch.", verify(ts_ok=False)),
        ("All tests pass.", verify(go_ok=None, ts_ok=None)),
    ],
)
def test_reconcile_adds_no_note_otherwise(summary, result):
    assert hygiene.reconcile([finding()], summary, result).verify_note is None
