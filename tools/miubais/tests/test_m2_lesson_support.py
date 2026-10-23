import pytest
from harnesskit import TraceLine
from miubais.paths import course_dir


@pytest.fixture
def lessons(monkeypatch):
    monkeypatch.syspath_prepend(str(course_dir() / "m2-evals-lab" / "lesson_support" / "src"))
    import evals_lab_lessons

    return evals_lab_lessons


def test_kappa_is_zero_when_one_side_always_says_the_majority(lessons):
    human = ["success"] * 9 + ["loop"]
    judge = ["success"] * 10
    agreement = lessons.kappa(human, judge)
    assert agreement.po == pytest.approx(0.9)
    assert agreement.kappa == pytest.approx(0.0)


def test_kappa_is_one_on_identical_labels(lessons):
    labels = ["loop", "success", "context-loss", "success"]
    assert lessons.kappa(labels, labels).kappa == pytest.approx(1.0)


def test_confusion_uses_pass_as_positive(lessons):
    c = lessons.confusion(["pass", "pass", "fail", "fail"], ["pass", "fail", "fail", "pass"])
    assert (c.tp, c.fp, c.tn, c.fn) == (1, 1, 1, 1)
    assert lessons.tpr(c) == 0.5
    assert lessons.tnr(c) == 0.5


def test_trusted_needs_forty_traces(lessons):
    assert lessons.trusted(0.9, 0.9, 0.7, 40)
    assert not lessons.trusted(0.9, 0.9, 0.7, 39)
    assert not lessons.trusted(0.9, 0.84, 0.7, 40)


def test_axial_code_counts_a_trace_once_per_category(lessons):
    axial = {"same edit twice": "loop", "reran same test": "loop"}
    notes = [lessons.Note("a", "fail", ("same edit twice", "reran same test"))]
    rows = lessons.axial_code(notes, axial)
    assert rows == [lessons.TaxonomyRow("loop", 1, 1)]


def test_stratified_split_keeps_every_id_once_and_is_seeded(lessons):
    strata = {f"x{i:03d}": "a" if i < 60 else "b" for i in range(100)}
    fractions = {"train": 0.2, "dev": 0.4, "test": 0.4}
    one = lessons.stratified_split(strata, fractions, seed=7)
    two = lessons.stratified_split(strata, fractions, seed=7)
    assert one == two
    assert sorted(i for ids in one.values() for i in ids) == sorted(strata)
    assert sum(strata[i] == "a" for i in one["train"]) == 12
    assert lessons.manifest_hash(one) == lessons.manifest_hash(two)


def test_new_categories_per_batch_counts_only_first_sightings(lessons):
    axial = {"a": "loop", "b": "success"}
    notes = [lessons.Note(f"n{i}", "fail", (code,)) for i, code in enumerate("abba")]
    assert lessons.new_categories_per_batch(notes, axial, size=2) == [2, 0]


def test_taxonomy_table_shows_share_and_survives_zero_total(lessons):
    rows = [lessons.TaxonomyRow("loop", 1, 1)]
    assert lessons.taxonomy_table(rows, total=4).splitlines()[-1].split() == [
        "loop",
        "1",
        "1",
        "25%",
    ]
    assert lessons.taxonomy_table(rows, total=0).splitlines()[-1].endswith("0%")


def test_split_counts_has_a_row_per_stratum_and_a_total(lessons):
    strata = {"x1": "a", "x2": "a", "x3": "b"}
    table = lessons.split_counts({"dev": ["x1", "x3"], "test": ["x2"]}, strata)
    assert [line.split() for line in table.splitlines()[2:]] == [
        ["a", "1", "1"],
        ["b", "1", "0"],
        ["total", "2", "1"],
    ]


def test_pass_at_k_and_pass_hat_k_match_the_tau_bench_estimators(lessons):
    assert lessons.pass_at_k(5, 3, 1) == pytest.approx(0.6)
    assert lessons.pass_hat_k(5, 3, 1) == pytest.approx(0.6)
    assert lessons.pass_at_k(5, 3, 3) == pytest.approx(1.0)
    assert lessons.pass_hat_k(5, 3, 3) == pytest.approx(0.1)
    assert lessons.pass_hat_k(5, 4, 5) == 0.0
    assert lessons.pass_at_k(5, 0, 5) == 0.0


def test_pass_at_k_rejects_k_larger_than_n(lessons):
    with pytest.raises(ValueError):
        lessons.pass_at_k(3, 1, 4)
    with pytest.raises(ValueError):
        lessons.pass_hat_k(3, 4, 1)


def test_suite_metrics_average_over_tasks(lessons):
    runs = {"a": [True] * 5, "b": [True, False, False, False, False]}
    assert lessons.suite_pass_at_k(runs, 1) == pytest.approx(0.6)
    assert lessons.suite_pass_hat_k(runs, 5) == pytest.approx(0.5)
    assert lessons.suite_pass_at_k(runs, 5) == pytest.approx(1.0)


def test_trajectory_finds_edits_test_runs_and_repeats(lessons):
    lines = [
        TraceLine(n=1, role="user", text="fix it"),
        TraceLine(n=2, role="assistant", tool="Bash", input={"command": "uv run pytest -q"}),
        TraceLine(n=3, role="assistant", tool="Edit", input={"file_path": "src/a.py"}),
        TraceLine(n=4, role="assistant", tool="Edit", input={"file_path": "tests/test_a.py"}),
        TraceLine(n=5, role="tool", tool="Edit", output="ok"),
    ]
    t = lessons.trajectory(lines)
    assert (t.edits, t.test_file_edits, t.test_runs, t.most_repeated_call) == (
        (3, 4),
        (4,),
        (2,),
        1,
    )
    assert lessons.trajectory_checks(t) == {
        "tests ran after the last edit": False,
        "no test file edited": False,
        "no call repeated more than 2 times": True,
    }


def test_gate_check_uses_whole_ten_thousandths(lessons):
    base = {"pass_rate": 0.445, "counts": {"loop": 10}}
    assert 0.445 - 0.425 > 0.02
    assert lessons.gate_check({"pass_rate": 0.425, "counts": {"loop": 10}}, base).ok
    late = lessons.gate_check({"pass_rate": 0.4249, "counts": {"loop": 10}}, base)
    assert not late.ok and "pass_rate" in late.reasons[0]
    assert lessons.gate_check({"pass_rate": 0.445, "counts": {"loop": 13}}, base).ok
    rise = lessons.gate_check({"pass_rate": 0.445, "counts": {"loop": 14}}, base)
    assert rise.reasons == ("loop rose from 10 to 14 (more than 3)",)


def test_gate_check_counts_a_new_category_from_zero(lessons):
    base = {"pass_rate": 0.5, "counts": {}}
    verdict = lessons.gate_check({"pass_rate": 0.5, "counts": {"loop": 4}}, base)
    assert verdict.reasons == ("loop rose from 0 to 4 (more than 3)",)


def test_review_scores_match_within_tolerance_once_per_label(lessons):
    F = lessons.Finding
    labels = [F("p1", "a.go", 10, "blocker"), F("p1", "a.go", 40, "minor")]
    reported = [
        F("p1", "a.go", 12, "blocker"),
        F("p1", "a.go", 11, "blocker"),
        F("p1", "b.go", 40, "minor"),
    ]
    pairs = lessons.match_findings(reported, labels)
    assert pairs == [(reported[1], labels[0])]
    scores = lessons.review_scores(reported, labels)
    assert scores["all"] == lessons.ReviewScore(3, 1, 2, 1)
    assert scores["blocker"].precision == pytest.approx(0.5)
    assert scores["blocker"].recall == 1.0
    assert scores["minor"].recall == 0.0 and scores["minor"].f1 == 0.0
    assert scores["all"].f1 == pytest.approx(2 * (1 / 3) * 0.5 / (1 / 3 + 0.5))


def test_review_table_has_a_row_per_severity_and_survives_empty(lessons):
    table = lessons.review_table(lessons.review_scores([], [lessons.Finding("p", "f", 1, "major")]))
    assert [line.split()[0] for line in table.splitlines()[2:]] == ["major", "all"]
    assert table.splitlines()[-1].split()[-3:] == ["0.00", "0.00", "0.00"]


def test_trajectory_flags_the_same_call_three_times(lessons):
    same = {"command": "uv run pytest tests/test_a.py"}
    lines = [TraceLine(n=i, role="assistant", tool="Bash", input=same) for i in (1, 2, 3)]
    checks = lessons.trajectory_checks(lessons.trajectory(lines))
    assert checks["no call repeated more than 2 times"] is False
    assert checks["tests ran after the last edit"] is True


def test_ten_thousandths_rounds_float_noise_to_whole_units(lessons):
    assert lessons.ten_thousandths(0.445) == 4450
    assert lessons.ten_thousandths(0.425) == 4250
    assert lessons.ten_thousandths(0.445) - lessons.ten_thousandths(0.425) == 200
    assert lessons.ten_thousandths(0.44504) == 4450
    assert lessons.ten_thousandths(0.42496) == 4250
