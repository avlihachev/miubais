import pytest
from capstone import filter as hygiene
from capstone import metrics
from capstone.review import FakeReviewer, changed_files
from capstone.types import Finding, Label, Matches, MetricsReport, Score


def finding(file="a.go", line=10, category="error-swallowed", confidence=0.8, severity="major"):
    return Finding(
        file=file,
        line=line,
        severity=severity,
        category=category,
        message=f"{category} at {file}:{line}",
        confidence=confidence,
    )


def label(file="a.go", start=10, end=12, category="error-swallowed", severity="major"):
    return Label(file=file, start=start, end=end, category=category, severity=severity)


@pytest.fixture
def per_pr(fake_review, prs, labels):
    reviewer = FakeReviewer(fake_review)

    def build(clean):
        out = {}
        for pr in prs:
            found = reviewer.review(pr, pr.dir, []).findings
            if clean:
                found = hygiene.clean(found, changed_files(pr.patch.read_text()))
            truth = [metrics.Label(**d) for d in labels[pr.id]["findings"]]
            out[pr.id] = metrics.match(found, truth)
        return out

    return build


def test_label_is_the_shared_type():
    assert metrics.Label is Label


@pytest.mark.parametrize(
    ("line", "hit"), [(6, False), (7, True), (11, True), (15, True), (16, False)]
)
def test_a_finding_matches_within_three_lines_of_the_label(line, hit):
    got = metrics.match([finding(line=line)], [label(start=10, end=12)])
    assert len(got.pairs) == (1 if hit else 0)


def test_file_and_category_must_be_equal():
    truth = [label()]
    for wrong in (finding(file="b.go"), finding(category="style"), finding(file="src/a.go")):
        got = metrics.match([wrong], truth)
        assert got.pairs == [] and got.unmatched_findings == [wrong]
        assert got.unmatched_labels == truth


def test_severity_does_not_decide_a_match():
    got = metrics.match([finding(severity="minor")], [label(severity="blocker")])
    assert len(got.pairs) == 1


def test_one_label_takes_one_finding_the_most_confident():
    low, high = finding(line=10, confidence=0.7), finding(line=11, confidence=0.9)
    truth = label()
    got = metrics.match([low, high], [truth])
    assert got.pairs == [(high, truth)]
    assert got.unmatched_findings == [low]
    assert got.unmatched_labels == []


def test_one_finding_takes_one_label():
    one = finding(line=11)
    first, second = label(start=10, end=11), label(start=12, end=13)
    got = metrics.match([one], [first, second])
    assert got.pairs == [(one, first)]
    assert got.unmatched_labels == [second]


def test_two_findings_fill_two_nearby_labels():
    a, b = finding(line=34, confidence=0.9), finding(line=38, confidence=0.8)
    near, far = label(start=34, end=35), label(start=38, end=39)
    got = metrics.match([a, b], [near, far])
    assert got.pairs == [(a, near), (b, far)]
    assert got.unmatched_findings == [] and got.unmatched_labels == []


def test_unmatched_lists_keep_input_order():
    x, y = finding("x.go", confidence=0.6), finding("y.go", confidence=0.9)
    p, q = label("p.go"), label("q.go")
    got = metrics.match([x, y], [p, q])
    assert got.unmatched_findings == [x, y] and got.unmatched_labels == [p, q]


def test_precision_recall_overall_and_by_severity():
    tp_blocker = finding("a.go", 1, "secret-in-code", 0.9, "blocker")
    fp_minor = finding("a.go", 50, "style", 0.7, "minor")
    hit = label("a.go", 1, 1, "secret-in-code", "blocker")
    missed = label("b.go", 5, 5, "test-removed", "major")
    got = metrics.match([tp_blocker, fp_minor], [hit, missed])
    assert metrics.precision_recall(got) == Score(0.5, 0.5, 0.5, 2, 2)
    blocker = metrics.precision_recall(got, "blocker")
    assert (blocker.precision, blocker.recall, blocker.n_findings, blocker.n_labels) == (
        1.0,
        1.0,
        1,
        1,
    )
    major = metrics.precision_recall(got, "major")
    assert (major.precision, major.recall, major.f1) == (1.0, 0.0, 0.0)
    minor = metrics.precision_recall(got, "minor")
    assert (minor.precision, minor.recall, minor.n_labels) == (0.0, 1.0, 0)
    assert metrics.blocker_recall(got) == 1.0


def test_nothing_claimed_and_nothing_to_find_scores_one():
    empty = metrics.precision_recall(Matches([], [], []))
    assert (empty.precision, empty.recall, empty.f1) == (1.0, 1.0, 1.0)


def test_f1_is_the_harmonic_mean():
    got = metrics.match(
        [finding(line=10), finding("b.go"), finding("c.go")], [label(), label("d.go")]
    )
    score = metrics.precision_recall(got)
    assert score.precision == pytest.approx(1 / 3) and score.recall == 0.5
    assert score.f1 == pytest.approx(0.4)


def test_the_recorded_reviewer_after_clean(per_pr):
    report = metrics.summarise(per_pr(clean=True))
    assert isinstance(report, MetricsReport)
    expected = {
        None: (11 / 16, 11 / 12, 16, 12),
        "blocker": (5 / 5, 5 / 5, 5, 5),
        "major": (5 / 7, 5 / 5, 7, 5),
        "minor": (1 / 4, 1 / 2, 4, 2),
    }
    for severity, (precision, recall, n_findings, n_labels) in expected.items():
        score = report.overall if severity is None else report.by_severity[severity]
        assert score.precision == pytest.approx(precision), severity
        assert score.recall == pytest.approx(recall), severity
        assert (score.n_findings, score.n_labels) == (n_findings, n_labels), severity
        assert score.f1 == pytest.approx(2 * precision * recall / (precision + recall))
    assert set(report.by_severity) == {"blocker", "major", "minor"}
    assert report.blocker_recall == 1.0
    assert metrics.trusted(report)


def test_the_recorded_reviewer_unfiltered_is_not_trusted(per_pr):
    report = metrics.summarise(per_pr(clean=False))
    assert report.overall.precision == pytest.approx(12 / 26)
    assert report.overall.recall == 1.0 and report.blocker_recall == 1.0
    assert not metrics.trusted(report)


def test_summarise_pools_the_prs(per_pr):
    pooled = per_pr(clean=True)
    report = metrics.summarise(pooled)
    assert report.overall.n_findings == sum(
        len(m.pairs) + len(m.unmatched_findings) for m in pooled.values()
    )
    assert report.overall.n_labels == sum(
        len(m.pairs) + len(m.unmatched_labels) for m in pooled.values()
    )


def report(precision, blocker_recall):
    overall = Score(precision, 1.0, 0.0, 10, 10)
    return MetricsReport(overall=overall, by_severity={}, blocker_recall=blocker_recall)


@pytest.mark.parametrize(
    ("precision", "blocker_recall", "ok"),
    [(0.6, 0.9, True), (0.59, 1.0, False), (1.0, 0.89, False), (0.6875, 1.0, True)],
)
def test_trusted_needs_precision_and_blocker_recall(precision, blocker_recall, ok):
    assert metrics.trusted(report(precision, blocker_recall)) is ok


def test_trusted_flips_when_false_positives_push_precision_below_point_six(per_pr):
    pooled = per_pr(clean=True)
    noise = [finding(f"noise{i}.go", 1, "style", 0.9, "minor") for i in range(3)]
    pooled["pr-01"] = Matches(
        pooled["pr-01"].pairs,
        pooled["pr-01"].unmatched_findings + noise,
        pooled["pr-01"].unmatched_labels,
    )
    noisy = metrics.summarise(pooled)
    assert noisy.overall.precision == pytest.approx(11 / 19)
    assert not metrics.trusted(noisy)
