import json

import pytest
from miubais.paths import course_dir, repo_root

LAB = course_dir() / "m7-capstone"


@pytest.fixture
def lessons(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB / "starter" / "src"))
    monkeypatch.syspath_prepend(str(LAB / "lesson_support" / "src"))
    import capstone_lessons

    return capstone_lessons


@pytest.fixture
def types(lessons):
    from capstone import types

    return types


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("**/*.ts", "web/src/api.ts", True),
        ("**/*.ts", "api.ts", True),
        ("src/**/*", "src/c.go", True),
        ("src/**/*", "websrc/x", False),
        ("*.json", "web/tsconfig.json", False),
        ("web/**/*.{ts,tsx}", "web/a/b.tsx", True),
        ("a/{b,{c,d}}/x", "a/d/x", True),
        ("migrations/000?_*.sql", "migrations/0010_x.sql", False),
    ],
)
def test_glob_matches(lessons, pattern, path, expected):
    assert lessons.glob_matches(pattern, path) is expected


def test_star_only_globstar_misses_nested_and_root_files(lessons):
    assert not lessons.glob_matches("**/*.ts", "web/src/api.ts", globstar=False)
    assert not lessons.glob_matches("**/*.ts", "api.ts", globstar=False)
    assert lessons.glob_matches("**/*.ts", "web/api.ts", globstar=False)


def test_fixture_rules_and_selection(lessons):
    rules = lessons.load_rules(repo_root() / "fixtures" / "go-ts-mini")
    assert [r.name for r in rules] == ["api", "changelog", "migrations", "proto", "web"]
    assert {r.name: r.paths for r in rules}["web"] == ("web/**/*.{ts,tsx}",)
    assert lessons.rules_for(rules, ["web/src/x.tsx", "internal/api/a.go"]) == [
        "changelog",
        "api",
        "web",
    ]
    assert lessons.rules_for(rules, ["README.md"]) == ["changelog"]


def test_changed_paths_include_deletions_once(lessons):
    patch = "--- a/x.go\n+++ b/x.go\n--- a/y.ts\n+++ /dev/null\n"
    assert lessons.changed_paths(patch) == ["x.go", "y.ts"]


def test_accept_findings_names_the_rejected_field(lessons):
    good = {
        "file": "a.go",
        "line": 3,
        "severity": "major",
        "category": "style",
        "message": "0123456789",
    }
    accepted, rejected = lessons.accept_findings(
        [{**good, "confidence": 0.5}, {**good, "confidence": 0.5, "line": 0}]
    )
    assert len(accepted) == 1 and rejected == ["a.go:0 rejected on line"]


def make(types, file, line, category, confidence, severity="major"):
    return types.Finding(
        file=file,
        line=line,
        severity=severity,
        category=category,
        message="a long enough message",
        confidence=confidence,
    )


def test_matching_rule_window_category_and_one_to_one(lessons, types):
    label = types.Label(file="a.go", start=10, end=12, category="style", severity="minor")
    findings = [
        make(types, "a.go", 15, "style", 0.6),
        make(types, "a.go", 7, "style", 0.9),
        make(types, "a.go", 11, "ts-any", 0.99),
        make(types, "a.go", 16, "style", 0.99),
    ]
    assert lessons.pair_up(findings, [label]) == [(1, 0)]
    scored = lessons.score(findings, [label], [(1, 0)])
    assert (scored.precision, scored.recall, scored.findings) == (0.25, 1.0, 4)


def test_file_only_rule_credits_a_distant_finding(lessons, types):
    label = types.Label(file="a.go", start=10, end=10, category="style", severity="minor")
    far = [make(types, "a.go", 90, "ts-any", 0.8)]
    assert lessons.pair_up(far, [label]) == []
    assert lessons.pair_up(far, [label], lessons.same_file) == [(0, 0)]


def test_score_by_severity_and_empty_sets(lessons, types):
    label = types.Label(file="a.go", start=1, end=1, category="style", severity="blocker")
    blocker = lessons.score([], [label], [], "blocker")
    assert (blocker.precision, blocker.recall, blocker.f1) == (1.0, 0.0, 0.0)
    assert lessons.score([], [], []).f1 == 1.0


def test_blockers_weights_rank_and_verdict(lessons):
    s = lessons.Signals
    rows = lessons.rank_prs(
        [
            s("ok", touches=("web/a.ts",), approvals=1),
            s(
                "gap",
                existing_migrations=(1, 2),
                new_migrations=(4,),
                approvals=2,
                touches=("migrations/0004_x.sql",),
            ),
            s("conflict", applied=False, tests_failed=True, touches=("proto/a.proto",)),
            s("old", age_days=15),
            s("young", age_days=14),
            s("major", finding_severities=("major",)),
        ]
    )
    by_pr = {r.pr: r for r in rows}
    assert [r.pr for r in rows][:3] == ["conflict", "gap", "old"]
    assert by_pr["conflict"].kinds == ("conflict", "missing-second-approval")
    assert by_pr["conflict"].score == 160 and by_pr["conflict"].verdict == "block"
    assert by_pr["gap"].kinds == ("stale-migration",)
    assert by_pr["old"].verdict == "hold" and by_pr["young"].verdict == "merge"
    assert by_pr["major"].score == 0 and by_pr["major"].verdict == "hold"
    assert lessons.verdict([], ["blocker"]) == "block"


def test_live_summary_aggregates_the_record(lessons):
    live = lessons.live_summary(LAB / "fixtures" / "live_review_run.json")
    assert live["total_usd"] == 0.7013 and live["reviewed"] == 11
    assert live["verdicts"] == {"merge": 1, "hold": 3, "block": 8}
    assert (live["findings"], live["noise"], live["agree_with_key"]) == (19, 8, 10)
    assert live["blocker_recall"] == 0.8 and live["wall_seconds"] == pytest.approx(130.733)
    assert 0.03 < live["usd_min"] < live["usd_max"] < 0.10
    v1 = lessons.live_summary(LAB / "fixtures" / "live_review_run_v1.json")
    assert v1["total_usd"] == 0.7206 and (v1["findings"], v1["noise"]) == (17, 7)


RECORD_KEYS = [
    "date",
    "stage",
    "reviewer",
    "model",
    "max_budget_usd_per_pr",
    "max_turns",
    "as_of",
    "prs",
    "metrics",
    "verdicts_agreeing_with_key",
    "totals",
]
RECORD_PR_KEYS = [
    "pr",
    "verdict",
    "reason",
    "review",
    "verify",
    "blockers",
    "findings",
    "cost_usd",
    "turns",
    "duration_ms",
]


@pytest.mark.parametrize("name", ["live_review_run.json", "live_review_run_v1.json"])
def test_committed_live_records_have_the_shape_record_emits(lessons, name):
    record = json.loads((LAB / "fixtures" / name).read_text())
    assert list(record) == RECORD_KEYS
    assert all(list(p) == RECORD_PR_KEYS for p in record["prs"])
    assert (record["model"], record["max_budget_usd_per_pr"], record["max_turns"]) == (
        "claude-opus-5-5",
        0.4,
        20,
    )
    assert lessons.live_summary(LAB / "fixtures" / name)["prs"] == 12
