import json
import re
import sys

import pytest
import yaml
from miubais.paths import course_dir, repo_root

LAB = course_dir() / "m2-evals-lab"
LESSONS = repo_root() / "site" / "src" / "content" / "docs" / "m2"
pytestmark = pytest.mark.skipif(
    not (LAB / "reference").is_dir(), reason="reference solutions are private"
)


@pytest.fixture
def reference(monkeypatch):
    for name in [m for m in sys.modules if m == "evals_lab" or m.startswith("evals_lab.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(LAB / "reference" / "src"))
    from evals_lab import labels, metrics, types

    yield labels, metrics, types
    for name in [m for m in sys.modules if m == "evals_lab" or m.startswith("evals_lab.")]:
        del sys.modules[name]


def test_fake_judge_numbers_cited_in_lesson_02(reference):
    labels, metrics, types = reference
    gold = yaml.safe_load((LAB / "tests" / "GOLD.yaml").read_text())
    fake = yaml.safe_load((LAB / "tests" / "FAKEJUDGE.yaml").read_text())
    gold_labels = labels.Labels(
        entries={
            k: labels.Label(outcome=v["outcome"], category=v["category"]) for k, v in gold.items()
        }
    )
    run = types.Run(
        run_id="fake",
        at="2026-10-17T00:00:00+00:00",
        judgements={k: types.Judgement(**v) for k, v in fake.items()},
    )
    report = metrics.report(run, gold_labels)
    assert report.n == 200
    assert (round(report.tpr, 2), round(report.tnr, 2), round(report.kappa, 2)) == (
        0.93,
        0.94,
        0.92,
    )


def test_live_judge_record_matches_lesson_02():
    record = json.loads((LAB / "fixtures" / "live_judge_run.json").read_text())
    assert record["model"] == "claude-opus-5-5"
    assert (record["n"], record["outcome_agreement"], record["category_agreement"]) == (20, 20, 19)
    assert round(record["cost_usd"], 2) == 0.27
    assert not {"judgements", "traces", "ids"} & record.keys()


def test_second_live_judge_record_matches_the_lessons():
    record = json.loads((LAB / "fixtures" / "live_judge_run_2.json").read_text())
    assert record["model"] == "claude-opus-5-5"
    assert (record["n"], record["outcome_agreement"], record["category_agreement"]) == (20, 20, 19)
    assert (record["failures"], record["cost_usd"]) == (0, 0.4235)
    assert not {"judgements", "traces", "ids"} & record.keys()


def lesson(name: str) -> str:
    return next(LESSONS.glob(f"{name}-*.md*")).read_text()


@pytest.mark.parametrize(
    ("name", "cited"),
    [
        ("02", ["0.93", "0.94", "0.92", "20 of 20", "19 of 20", "$0.2717", "$0.4235"]),
        ("03", ["0.565", "0.58"]),
        ("05", ["0.93", "0.94", "0.92", "$0.2717", "$0.4235"]),
        ("07", ["$0.2717", "$0.4235"]),
    ],
)
def test_lessons_cite_the_recomputed_numbers(name, cited):
    text = lesson(name)
    assert [n for n in cited if n not in text] == []


def test_readme_hand_label_ids_match_the_stage_list():
    readme = (LAB / "README.md").read_text()
    block = readme.split("## Hand labels stage", 1)[1].split("```", 2)[1]
    lists = yaml.safe_load((LAB / "tests" / "STAGE_LISTS.yaml").read_text())
    assert block.split() == lists["hand_labels"]


def test_no_label_example_names_a_real_trace():
    docs = [LAB / "README.md", repo_root() / "fixtures" / "evals-traces" / "README.md"]
    docs += sorted(LESSONS.glob("*.md*"))
    example = re.compile(r'"trace":\s*"t\d{3}"')
    assert [str(d) for d in docs if example.search(d.read_text())] == []
