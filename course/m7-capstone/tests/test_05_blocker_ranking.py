from dataclasses import replace
from datetime import date

import pytest
from capstone import blockers
from capstone.review import changed_files
from capstone.types import BLOCKER_KINDS, Applied, Blocker, VerifyResult

AS_OF = date(2026, 10, 17)
OUTCOMES = {
    "pr-07": VerifyResult(go_ok=True, ts_ok=False, output="", duration_ms=1),
    "pr-09": VerifyResult(go_ok=False, ts_ok=True, output="", duration_ms=1),
}
PASSED = VerifyResult(go_ok=True, ts_ok=True, output="", duration_ms=1)


def signals(pr, repo):
    if pr.id == "pr-10":
        return Applied(ok=False, conflicts=["internal/api/errors.go"], tree=repo), None
    return Applied(ok=True, conflicts=[], tree=repo), OUTCOMES.get(pr.id, PASSED)


def detect(pr, repo, changed=None, applied=None, verify=None, as_of=AS_OF):
    base_applied, base_verify = signals(pr, repo)
    return blockers.detect(
        pr,
        repo,
        changed_files(pr.patch.read_text()) if changed is None else changed,
        applied or base_applied,
        verify if verify is not None else base_verify,
        as_of=as_of,
    )


def kinds(found):
    return sorted(b.kind for b in found)


@pytest.fixture
def by_id(prs):
    return {pr.id: pr for pr in prs}


def test_every_pr_gets_exactly_its_labelled_blockers(prs, repo, labels):
    for pr in prs:
        assert kinds(detect(pr, repo)) == sorted(labels[pr.id]["blockers"]), pr.id


def test_each_kind_fires_on_one_pr_and_carries_its_weight(prs, repo):
    seen = {}
    for pr in prs:
        for b in detect(pr, repo):
            assert b.weight == blockers.WEIGHTS[b.kind]
            assert b.detail
            seen.setdefault(b.kind, []).append(pr.id)
    assert seen == {
        "conflict": ["pr-10"],
        "verify-failed": ["pr-07", "pr-09"],
        "stale-migration": ["pr-04"],
        "missing-second-approval": ["pr-03"],
        "unreviewed-age": ["pr-11"],
    }
    assert set(seen) == set(BLOCKER_KINDS)


def test_weights_are_the_course_weights():
    assert blockers.WEIGHTS == {
        "conflict": 100,
        "verify-failed": 90,
        "stale-migration": 80,
        "missing-second-approval": 60,
        "unreviewed-age": 30,
    }


def test_conflict_names_the_files_and_verify_failed_names_the_side(by_id, repo):
    (conflict,) = detect(by_id["pr-10"], repo)
    assert "internal/api/errors.go" in conflict.detail
    (ts,) = detect(by_id["pr-07"], repo)
    assert "node --test" in ts.detail and "go test" not in ts.detail
    (go,) = detect(by_id["pr-09"], repo)
    assert "go test" in go.detail and "node --test" not in go.detail


def test_no_verify_result_or_missing_tools_is_not_a_failure(by_id, repo):
    pr = by_id["pr-01"]
    applied = Applied(ok=True, conflicts=[], tree=repo)
    assert blockers.detect(pr, repo, [], applied, None, as_of=AS_OF) == []
    unknown = VerifyResult(go_ok=None, ts_ok=None, output="", duration_ms=0)
    assert blockers.detect(pr, repo, [], applied, unknown, as_of=AS_OF) == []


def test_a_web_only_pr_with_one_approval_is_not_held(by_id, repo):
    for pr_id in ("pr-01", "pr-07", "pr-08"):
        pr = by_id[pr_id]
        assert len(pr.approvals) == 1
        assert "missing-second-approval" not in kinds(detect(pr, repo)), pr_id
    one = by_id["pr-03"]
    web = ["web/src/format.ts", "CHANGELOG.json", "internal/api/handlers.go"]
    assert detect(one, repo, changed=web) == []


@pytest.mark.parametrize(
    "path",
    [
        "proto/jobs/v1/jobs.proto",
        "migrations/0005_add_notes.sql",
        ".claude/rules/api.md",
        ".claude/settings.json",
    ],
)
def test_proto_and_migrations_need_two_approvals(by_id, repo, path):
    pr = by_id["pr-01"]
    assert kinds(detect(pr, repo, changed=[path])) == ["missing-second-approval"]
    two = replace(pr, approvals=["bruno", "chen"])
    assert detect(two, repo, changed=[path]) == []


@pytest.mark.parametrize(
    ("changed", "stale"),
    [
        (["migrations/0005_add_notes.sql"], False),
        (["migrations/0005_add_notes.sql", "migrations/0006_add_tags.sql"], False),
        (["migrations/0002_add_due_at.sql"], False),
        (["migrations/0006_add_notes.sql"], True),
        (["migrations/0004_add_due_at_index.sql"], True),
        (["migrations/0003_add_notes.sql"], True),
        (["migrations/0005_add_notes.sql", "migrations/0005_add_tags.sql"], True),
    ],
)
def test_stale_migration_is_a_new_number_out_of_sequence(by_id, repo, changed, stale):
    pr = replace(by_id["pr-02"], approvals=["aino", "chen"])
    assert kinds(detect(pr, repo, changed=changed)) == (["stale-migration"] if stale else [])


@pytest.mark.parametrize(
    ("created", "approvals", "aged"),
    [
        (date(2026, 10, 3), [], False),
        (date(2026, 10, 2), [], True),
        (date(2026, 9, 20), ["chen"], False),
        (date(2026, 9, 20), [], True),
    ],
)
def test_unreviewed_age_is_over_fourteen_days_without_approvals(
    by_id, repo, created, approvals, aged
):
    pr = replace(by_id["pr-11"], created_at=created, approvals=approvals)
    assert kinds(detect(pr, repo)) == (["unreviewed-age"] if aged else [])


def test_as_of_is_the_clock(by_id, repo):
    pr = by_id["pr-11"]
    assert detect(pr, repo, as_of=date(2026, 10, 1)) == []


def test_score_is_the_sum_of_weights():
    found = [
        Blocker(kind="conflict", detail="x", weight=100),
        Blocker(kind="unreviewed-age", detail="y", weight=30),
    ]
    assert blockers.score(found) == 130
    assert blockers.score([]) == 0


def test_rank_orders_by_score_then_id(prs, repo):
    ranked = blockers.rank([(pr, detect(pr, repo)) for pr in reversed(prs)])
    assert [(r.pr_id, r.score) for r in ranked] == [
        ("pr-10", 100),
        ("pr-07", 90),
        ("pr-09", 90),
        ("pr-04", 80),
        ("pr-03", 60),
        ("pr-11", 30),
        ("pr-01", 0),
        ("pr-02", 0),
        ("pr-05", 0),
        ("pr-06", 0),
        ("pr-08", 0),
        ("pr-12", 0),
    ]


def test_rank_lists_kinds_heaviest_first(by_id):
    found = [
        Blocker(kind="unreviewed-age", detail="", weight=30),
        Blocker(kind="conflict", detail="", weight=100),
        Blocker(kind="missing-second-approval", detail="", weight=60),
    ]
    (ranked,) = blockers.rank([(by_id["pr-03"], found)])
    assert ranked.score == 190
    assert ranked.kinds == ["conflict", "missing-second-approval", "unreviewed-age"]


def test_to_markdown_is_a_table_in_rank_order(prs, repo):
    ranked = blockers.rank([(pr, detect(pr, repo)) for pr in prs])
    lines = blockers.to_markdown(ranked).strip().splitlines()
    assert lines[0].replace(" ", "") == "|pr|score|blockers|"
    assert set(lines[1]) <= set("|-: ")
    rows = [[c.strip() for c in line.strip("|").split("|")] for line in lines[2:]]
    assert rows[0] == ["pr-10", "100", "conflict"]
    assert rows[4] == ["pr-03", "60", "missing-second-approval"]
    assert rows[-1] == ["pr-12", "0", "none"]
    assert [r[0] for r in rows] == [r.pr_id for r in ranked]
