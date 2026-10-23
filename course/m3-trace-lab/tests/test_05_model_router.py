import subprocess
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from harnesskit.policy import Policy
from harnesskit.report import RunReport
from harnesskit.sessions import SessionStore
from trace_lab import spans
from trace_lab.router import Route, Router
from trace_lab.types import Attempt

HAIKU = Route("haiku", "claude-haiku-5-5", max_budget_usd=0.10, max_turns=6)
SONNET = Route("sonnet", "claude-sonnet-5-5", max_budget_usd=0.40, max_turns=12)
OPUS = Route("opus", "claude-opus-5-5", max_budget_usd=1.00, max_turns=20)


def assistant(model, n):
    return AssistantMessage(
        content=[TextBlock(text="ok")],
        model=model,
        usage={
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 300,
            "cache_creation_input_tokens": 40,
        },
        message_id=f"{model}-{n}",
        stop_reason="end_turn",
        session_id="sess-1",
    )


def result(subtype, cost, turns=2):
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=8,
        is_error=subtype != "success",
        num_turns=turns,
        session_id="sess-1",
        total_cost_usd=cost,
    )


def report(model, stopped_by, cost, turns):
    return RunReport(
        ticket_id="001-discount-rounding",
        session_id="sess-1",
        turns=turns,
        cost_usd=cost,
        stopped_by=stopped_by,
        files_changed=[],
        tests_passed=None,
        verdict=None,
        messages=[assistant(model, n) for n in range(turns)],
    )


class FakeRun:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def __call__(self, ticket_path, repo, **kwargs):
        self.calls.append(kwargs)
        stopped_by, cost, turns = self.outcomes[kwargs["model"]]
        return report(kwargs["model"], stopped_by, cost, turns)


@pytest.fixture
def ticket(tmp_path: Path) -> Path:
    path = tmp_path / "001-discount-rounding.md"
    path.write_text("# Discount rounding\n\nFix it.\n")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"],
        check=True,
    )
    return root


def test_max_turns_on_haiku_falls_back_to_sonnet(ticket, repo):
    run = FakeRun({HAIKU.model: ("max_turns", 0.05, 6), SONNET.model: ("success", 0.21, 4)})
    routed = Router([HAIKU, SONNET, OPUS]).run(ticket, repo, run_fn=run, policy="p", store="s")
    assert routed.route == "sonnet"
    assert routed.attempts == [
        Attempt("haiku", "max_turns", 0.05),
        Attempt("sonnet", "success", 0.21),
    ]
    assert routed.report.stopped_by == "success"
    assert routed.report.cost_usd == 0.21
    assert run.calls == [
        {
            "model": HAIKU.model,
            "max_turns": 6,
            "max_budget_usd": 0.10,
            "policy": "p",
            "store": "s",
        },
        {
            "model": SONNET.model,
            "max_turns": 12,
            "max_budget_usd": 0.40,
            "policy": "p",
            "store": "s",
        },
    ]


@pytest.mark.parametrize("stopped_by", ["budget", "max_turns", "error"])
def test_each_fallback_class_moves_to_the_next_route(ticket, repo, stopped_by):
    run = FakeRun({HAIKU.model: (stopped_by, 0.1, 3), SONNET.model: ("success", 0.2, 3)})
    routed = Router([HAIKU, SONNET]).run(ticket, repo, run_fn=run)
    assert [a.route for a in routed.attempts] == ["haiku", "sonnet"]
    assert routed.route == "sonnet"


def test_policy_stop_ends_routing_with_one_attempt(ticket, repo):
    run = FakeRun({HAIKU.model: ("policy", 0.03, 2), SONNET.model: ("success", 0.2, 3)})
    router = Router([HAIKU, SONNET, OPUS])
    routed = router.run(ticket, repo, run_fn=run)
    assert routed.route == "haiku"
    assert routed.attempts == [Attempt("haiku", "policy", 0.03)]
    assert routed.report.stopped_by == "policy"
    assert [call["model"] for call in run.calls] == [HAIKU.model]
    assert router.stats["sonnet"].attempts == 0


def test_success_on_the_first_route_makes_one_attempt(ticket, repo):
    run = FakeRun({HAIKU.model: ("success", 0.04, 3)})
    routed = Router([HAIKU, SONNET]).run(ticket, repo, run_fn=run)
    assert routed.route == "haiku"
    assert len(routed.attempts) == 1


def test_when_every_route_fails_the_last_report_is_returned(ticket, repo):
    run = FakeRun(
        {
            HAIKU.model: ("max_turns", 0.05, 6),
            SONNET.model: ("budget", 0.40, 9),
            OPUS.model: ("error", 0.0, 1),
        }
    )
    routed = Router([HAIKU, SONNET, OPUS]).run(ticket, repo, run_fn=run)
    assert routed.route == "opus"
    assert routed.report.stopped_by == "error"
    assert routed.report.messages[0].model == OPUS.model
    assert [a.stopped_by for a in routed.attempts] == ["max_turns", "budget", "error"]


def test_a_narrower_fallback_set_stops_earlier(ticket, repo):
    run = FakeRun({HAIKU.model: ("error", 0.0, 1), SONNET.model: ("success", 0.2, 3)})
    routed = Router([HAIKU, SONNET], fallback_on=frozenset({"budget"})).run(
        ticket, repo, run_fn=run
    )
    assert routed.route == "haiku"
    assert len(routed.attempts) == 1


@pytest.mark.parametrize("bad", ["policy", "success"])
def test_policy_and_success_cannot_fall_back(bad):
    with pytest.raises(ValueError):
        Router([HAIKU, SONNET], fallback_on=frozenset({"budget", bad}))


@pytest.mark.parametrize("routes", [[], [HAIKU, HAIKU]])
def test_routes_must_be_present_and_uniquely_named(routes):
    with pytest.raises(ValueError):
        Router(routes)


def test_stats_accumulate_across_tickets(ticket, repo, tmp_path):
    other = tmp_path / "002-negative-quantity.md"
    other.write_text("# Negative quantity\n")
    router = Router([HAIKU, SONNET, OPUS])
    router.run(
        ticket,
        repo,
        run_fn=FakeRun({HAIKU.model: ("max_turns", 0.05, 6), SONNET.model: ("success", 0.21, 4)}),
    )
    router.run(other, repo, run_fn=FakeRun({HAIKU.model: ("success", 0.03, 2)}))
    haiku, sonnet, opus = (router.stats[name] for name in ("haiku", "sonnet", "opus"))
    assert (haiku.attempts, haiku.successes, haiku.turns) == (2, 1, 8)
    assert haiku.cost_usd == pytest.approx(0.08)
    assert (sonnet.attempts, sonnet.successes, sonnet.turns) == (1, 1, 4)
    assert sonnet.cost_usd == pytest.approx(0.21)
    assert (opus.attempts, opus.successes, opus.cost_usd, opus.turns) == (0, 0, 0.0, 0)


def test_to_markdown_has_a_header_and_a_row_per_route(ticket, repo):
    router = Router([HAIKU, SONNET])
    router.run(ticket, repo, run_fn=FakeRun({HAIKU.model: ("success", 0.03, 2)}))
    lines = router.to_markdown().strip().splitlines()
    assert len(lines) == 4
    header = [cell.strip() for cell in lines[0].strip("|").split("|")]
    assert {"route", "attempts", "successes", "cost_usd", "turns"} <= set(header)
    haiku = dict(zip(header, (c.strip() for c in lines[2].strip("|").split("|")), strict=True))
    assert haiku["route"] == "haiku"
    assert (haiku["attempts"], haiku["successes"], haiku["turns"]) == ("1", "1", "2")
    assert float(haiku["cost_usd"]) == pytest.approx(0.03)
    assert lines[3].strip("|").split("|")[0].strip() == "sonnet"


def test_each_attempt_is_traced_with_its_route(ticket, repo):
    provider, exporter = spans.provider_for_tests()
    run = FakeRun({HAIKU.model: ("max_turns", 0.05, 3), SONNET.model: ("success", 0.21, 2)})
    Router([HAIKU, SONNET], tracer_provider=provider).run(ticket, repo, run_fn=run)
    finished = exporter.get_finished_spans()
    roots = [s for s in finished if s.parent is None]
    assert [r.attributes["trace_lab.route"] for r in roots] == ["haiku", "sonnet"]
    assert all(r.attributes["trace_lab.ticket_id"] == "001-discount-rounding" for r in roots)
    assert len({r.context.trace_id for r in roots}) == 2
    for root, model, turns in zip(roots, [HAIKU.model, SONNET.model], [3, 2], strict=True):
        chats = [
            s for s in finished if s.parent is not None and s.parent.span_id == root.context.span_id
        ]
        assert [s.name for s in chats] == [f"chat {model}"] * turns


def test_the_route_reaches_the_sdk_options(scripted, ticket, repo, tmp_path):
    scripts = {
        HAIKU.model: [assistant(HAIKU.model, 0), result("error_max_turns", 0.05, turns=6)],
        SONNET.model: [assistant(SONNET.model, 0), result("success", 0.30)],
    }
    seen = []

    def query(prompt, options):
        seen.append(options)
        return scripted(scripts[options.model])(prompt, options)

    with SessionStore(tmp_path / "sessions.db") as store:
        routed = Router([HAIKU, SONNET]).run(
            ticket,
            repo,
            policy=Policy(writable=[repo / "src"]),
            store=store,
            query_fn=query,
        )
    assert [(o.model, o.max_turns, o.max_budget_usd) for o in seen] == [
        (HAIKU.model, 6, 0.10),
        (SONNET.model, 12, 0.40),
    ]
    assert seen[0].resume is None
    assert seen[1].resume == "sess-1"
    assert routed.attempts[0].stopped_by == "max_turns"
    assert routed.route == "sonnet"
    assert routed.report.stopped_by == "success"
    assert routed.report.resumed is True
    assert routed.report.cost_usd == pytest.approx(0.25)
