import pytest
from evals_lab import judge, traces
from evals_lab.judge import FakeJudge
from evals_lab.labels import Label, Labels
from evals_lab.metrics import confusion, kappa, report, tnr, tpr, trusted
from evals_lab.types import CATEGORIES, Confusion, Judgement, MetricsReport, Run


@pytest.fixture
def gold_labels(gold):
    return Labels(
        entries={i: Label(outcome=v["outcome"], category=v["category"]) for i, v in gold.items()}
    )


@pytest.fixture
def fake_run(traces_dir, fake_answers_path):
    return judge.run(FakeJudge(fake_answers_path), traces.load(traces_dir))


def make_run(pairs):
    return Run(
        "r",
        "2026-10-17T00:00:00+00:00",
        {i: Judgement(o, c, "x" * 20) for i, (o, c) in pairs.items()},
    )


def by_hand(gold, run):
    tp = fp = tn = fn = agree = 0
    judged, actual = {}, {}
    for trace_id, j in run.judgements.items():
        g = gold[trace_id]
        if j.outcome == "pass" and g["outcome"] == "pass":
            tp += 1
        elif j.outcome == "pass" and g["outcome"] == "fail":
            fp += 1
        elif j.outcome == "fail" and g["outcome"] == "fail":
            tn += 1
        else:
            fn += 1
        agree += j.category == g["category"]
        judged[j.category] = judged.get(j.category, 0) + 1
        actual[g["category"]] = actual.get(g["category"], 0) + 1
    n = len(run.judgements)
    po = agree / n
    pe = sum(judged.get(c, 0) * actual.get(c, 0) for c in CATEGORIES) / (n * n)
    return (tp, fp, tn, fn), tp / (tp + fn), tn / (tn + fp), (po - pe) / (1 - pe)


def test_confusion_counts_pass_as_positive():
    gold = Labels(
        entries={
            "a": Label(outcome="pass", category="success"),
            "b": Label(outcome="pass", category="success"),
            "c": Label(outcome="fail", category="loop"),
            "d": Label(outcome="fail", category="loop"),
            "e": Label(outcome="fail", category="loop"),
        }
    )
    run = make_run(
        {
            "a": ("pass", "success"),
            "b": ("fail", "loop"),
            "c": ("pass", "success"),
            "d": ("fail", "loop"),
            "e": ("fail", "loop"),
        }
    )
    assert confusion(run, gold) == Confusion(tp=1, fp=1, tn=2, fn=1)


def test_confusion_only_counts_traces_both_sides_know():
    gold = Labels(entries={"a": Label(outcome="pass", category="success")})
    run = make_run({"a": ("pass", "success"), "zzz": ("fail", "loop")})
    assert confusion(run, gold) == Confusion(tp=1, fp=0, tn=0, fn=0)


def test_rates_are_zero_when_the_denominator_is_zero():
    assert tpr(Confusion(tp=0, fp=3, tn=2, fn=0)) == 0.0
    assert tnr(Confusion(tp=2, fp=0, tn=0, fn=3)) == 0.0
    assert tpr(Confusion(tp=3, fp=0, tn=0, fn=1)) == pytest.approx(0.75)
    assert tnr(Confusion(tp=0, fp=1, tn=3, fn=0)) == pytest.approx(0.75)


def test_fake_judge_over_all_traces_matches_counting_by_hand(gold, gold_labels, fake_run):
    counts, hand_tpr, hand_tnr, hand_kappa = by_hand(gold, fake_run)
    assert len(fake_run.judgements) == 200
    assert confusion(fake_run, gold_labels) == Confusion(*counts)
    assert tpr(confusion(fake_run, gold_labels)) == pytest.approx(hand_tpr)
    assert tnr(confusion(fake_run, gold_labels)) == pytest.approx(hand_tnr)
    assert kappa(fake_run, gold_labels) == pytest.approx(hand_kappa, abs=1e-9)
    summary = report(fake_run, gold_labels)
    assert summary == MetricsReport(
        n=200,
        tpr=pytest.approx(hand_tpr),
        tnr=pytest.approx(hand_tnr),
        kappa=pytest.approx(hand_kappa, abs=1e-9),
    )


def test_the_fake_judge_is_trusted_over_all_traces(gold_labels, fake_run):
    assert trusted(report(fake_run, gold_labels)) is True


def test_perfect_agreement_is_trusted_at_forty_and_not_at_thirty_nine():
    assert trusted(MetricsReport(n=40, tpr=1.0, tnr=1.0, kappa=1.0)) is True
    assert trusted(MetricsReport(n=39, tpr=1.0, tnr=1.0, kappa=1.0)) is False
    assert trusted(MetricsReport(n=30, tpr=1.0, tnr=1.0, kappa=1.0)) is False


def test_trusted_uses_the_exact_thresholds():
    assert trusted(MetricsReport(n=40, tpr=0.85, tnr=0.85, kappa=0.6)) is True
    assert trusted(MetricsReport(n=40, tpr=0.8499, tnr=0.9, kappa=0.9)) is False
    assert trusted(MetricsReport(n=40, tpr=0.9, tnr=0.8499, kappa=0.9)) is False
    assert trusted(MetricsReport(n=40, tpr=0.9, tnr=0.9, kappa=0.5999)) is False


def test_perfect_judge_on_forty_traces_is_trusted(gold, gold_labels):
    ids = sorted(gold)[:40]
    perfect = make_run({i: (gold[i]["outcome"], gold[i]["category"]) for i in ids})
    summary = report(perfect, gold_labels)
    assert summary.n == 40
    assert (summary.tpr, summary.tnr) == (1.0, 1.0)
    assert summary.kappa == pytest.approx(1.0)
    assert trusted(summary) is True
    thirty_nine = make_run({i: (gold[i]["outcome"], gold[i]["category"]) for i in ids[:39]})
    assert trusted(report(thirty_nine, gold_labels)) is False


def test_right_outcome_wrong_category_fails_the_trust_gate(gold, gold_labels):
    rotate = {c: CATEGORIES[(k + 1) % len(CATEGORIES)] for k, c in enumerate(CATEGORIES)}
    wrong = make_run({i: (v["outcome"], rotate[v["category"]]) for i, v in gold.items()})
    summary = report(wrong, gold_labels)
    assert summary.n == 200
    assert (summary.tpr, summary.tnr) == (1.0, 1.0)
    assert summary.kappa < 0.6
    assert trusted(summary) is False


def test_a_run_sharing_no_trace_with_gold_reports_zero_and_is_untrusted(gold_labels):
    stranger = make_run({"zzz": ("pass", "success")})
    summary = report(stranger, gold_labels)
    assert summary == MetricsReport(n=0, tpr=0.0, tnr=0.0, kappa=0.0)
    assert trusted(summary) is False
