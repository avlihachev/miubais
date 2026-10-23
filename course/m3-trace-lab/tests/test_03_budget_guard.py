import subprocess
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from harnesskit.policy import Policy
from harnesskit.runner import run_ticket
from harnesskit.sessions import SessionStore
from trace_lab import budget
from trace_lab.cost import Prices

MODEL = "claude-opus-5-5"
USAGE = {
    "input_tokens": 1_200,
    "output_tokens": 300,
    "cache_read_input_tokens": 20_000,
    "cache_creation_input_tokens": 3_000,
}


def turn(n, *, tool_id=None, usage=USAGE):
    block = ToolUseBlock(id=tool_id, name="Read", input={}) if tool_id else TextBlock(text="ok")
    return AssistantMessage(
        content=[block],
        model=MODEL,
        usage=dict(usage),
        message_id=f"msg-{n}",
        stop_reason="tool_use" if tool_id else "end_turn",
        session_id="sess-1",
    )


def tool_result(tool_id):
    return UserMessage(content=[ToolResultBlock(tool_use_id=tool_id, content="x", is_error=False)])


def result(cost=0.4321):
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=False,
        num_turns=4,
        session_id="sess-1",
        total_cost_usd=cost,
    )


def stream():
    return [
        turn(1, tool_id="t1"),
        turn(1, tool_id="t2"),
        tool_result("t1"),
        tool_result("t2"),
        turn(2, tool_id="t3"),
        tool_result("t3"),
        turn(3, tool_id="t4"),
        tool_result("t4"),
        turn(4),
        result(),
    ]


def hand_cost(usage, price):
    return (
        usage["input_tokens"] * price["input"]
        + usage["output_tokens"] * price["output"]
        + usage["cache_read_input_tokens"] * price["cache_read"]
        + usage["cache_creation_input_tokens"] * price["cache_write_5m"]
    ) / 1e6


def running_estimates(messages, prices):
    seen, total, out = set(), 0.0, []
    for message in messages:
        if isinstance(message, AssistantMessage) and message.message_id not in seen:
            seen.add(message.message_id)
            total += hand_cost(message.usage, prices.table[message.model])
        out.append(total)
    return out


@pytest.fixture
def prices(prices_path):
    return Prices.load(prices_path)


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


@pytest.fixture
def ticket(tmp_path: Path) -> Path:
    path = tmp_path / "001-discount-rounding.md"
    path.write_text("# Discount rounding\n\nFix it.\n")
    return path


@pytest.fixture
def harness(tmp_path, repo):
    with SessionStore(tmp_path / "sessions.db") as store:
        yield {"policy": Policy(writable=[repo / "src"]), "store": store}


class Tracked:
    def __init__(self, scripted, items):
        self.reached_end = False
        self.options = []
        replay = scripted([*items[:-1], self._mark, items[-1]])

        def query(prompt, options):
            self.options.append(options)
            return replay(prompt, options)

        self.query = query

    async def _mark(self, _options):
        self.reached_end = True


def crossing(estimates, limit):
    return next(i for i, usd in enumerate(estimates) if usd > limit)


def test_guard_counts_each_turn_once(prices):
    guard = budget.BudgetGuard(10.0, prices)
    messages = stream()
    for message in messages:
        assert guard(message) is False
    assert guard.messages_seen == len(messages)
    assert guard.cost_usd == pytest.approx(running_estimates(messages, prices)[-1], abs=1e-12)
    assert guard.cost_usd == pytest.approx(4 * hand_cost(USAGE, prices.table[MODEL]), abs=1e-12)
    assert guard.tripped is False


def test_guard_trips_on_the_message_that_crosses_the_limit(prices):
    messages = stream()
    estimates = running_estimates(messages, prices)
    limit = (estimates[4] + estimates[6]) / 2
    index = crossing(estimates, limit)
    assert index == 6
    guard = budget.BudgetGuard(limit, prices)
    answers = [guard(message) for message in messages[: index + 1]]
    assert answers == [False] * index + [True]
    assert guard.tripped is True
    assert guard.cost_usd == pytest.approx(estimates[index], abs=1e-12)


def test_limit_equal_to_the_estimate_does_not_trip(prices):
    messages = stream()
    estimates = running_estimates(messages, prices)
    guard = budget.BudgetGuard(estimates[-1], prices)
    assert not any(guard(message) for message in messages)
    assert guard.tripped is False


def test_guard_skips_zero_usage_synthetic_messages(prices):
    zero = dict.fromkeys(USAGE, 0)
    synthetic = AssistantMessage(
        content=[TextBlock(text="API Error")], model="<synthetic>", usage=zero, message_id="msg-9"
    )
    guard = budget.BudgetGuard(10.0, prices)
    assert guard(synthetic) is False
    assert guard.cost_usd == 0.0 and guard.messages_seen == 1


def test_guard_names_an_unpriced_model(prices):
    unpriced = AssistantMessage(
        content=[TextBlock(text="ok")], model="claude-unpriced", usage=dict(USAGE), message_id="m"
    )
    with pytest.raises(KeyError, match="claude-unpriced"):
        budget.BudgetGuard(10.0, prices)(unpriced)


@pytest.mark.parametrize("cut", [0, 4, 6, 8])
def test_run_stops_at_the_crossing_message(prices, scripted, repo, ticket, harness, cut):
    messages = stream()
    estimates = running_estimates(messages, prices)
    previous = estimates[cut - 1] if cut else 0.0
    limit = (previous + estimates[cut]) / 2
    index = crossing(estimates, limit)
    assert index == cut
    tracked = Tracked(scripted, messages)
    guard = budget.BudgetGuard(limit, prices)
    report = run_ticket(ticket, repo, query_fn=tracked.query, observer=guard, **harness)
    assert report.stopped_by == "budget"
    assert "stopped by observer" in report.notes
    assert guard.tripped is True
    assert guard.messages_seen == index + 1
    assert report.messages == messages[: index + 1]
    assert not any(isinstance(m, ResultMessage) for m in report.messages)
    assert tracked.reached_end is False
    assert report.cost_usd == guard.cost_usd
    assert report.cost_usd == pytest.approx(estimates[index], abs=1e-12)


def test_run_with_budget_reports_the_estimate(prices, scripted, repo, ticket, harness):
    messages = stream()
    estimates = running_estimates(messages, prices)
    limit = (estimates[0] + estimates[4]) / 2
    tracked = Tracked(scripted, messages)
    report = budget.run_with_budget(
        ticket, repo, limit_usd=limit, prices=prices, query_fn=tracked.query, **harness
    )
    assert report.stopped_by == "budget"
    assert report.messages == messages[:5]
    assert report.cost_usd == pytest.approx(estimates[4], abs=1e-12)
    assert tracked.reached_end is False


def test_run_under_budget_succeeds_with_the_sdk_cost(prices, scripted, repo, ticket, harness):
    messages = stream()
    estimates = running_estimates(messages, prices)
    limit = 1.0
    assert estimates[-1] < messages[-1].total_cost_usd < limit
    tracked = Tracked(scripted, messages)
    report = budget.run_with_budget(
        ticket, repo, limit_usd=limit, prices=prices, query_fn=tracked.query, **harness
    )
    assert [o.max_budget_usd for o in tracked.options] == [limit]
    assert report.stopped_by == "success"
    assert report.cost_usd == messages[-1].total_cost_usd
    assert report.cost_usd != pytest.approx(estimates[-1])
    assert tracked.reached_end is True
    assert report.messages == messages


@pytest.mark.parametrize(("override", "expected"), [({}, 0.9), ({"max_budget_usd": 5.0}, 5.0)])
def test_the_limit_is_the_sdk_budget_unless_overridden(
    prices, scripted, repo, ticket, harness, override, expected
):
    tracked = Tracked(scripted, stream())
    budget.run_with_budget(
        ticket, repo, limit_usd=0.9, prices=prices, query_fn=tracked.query, **override, **harness
    )
    assert [o.max_budget_usd for o in tracked.options] == [expected]


def test_guard_ignores_messages_without_assistant_usage(prices):
    guard = budget.BudgetGuard(0.0, prices)
    others = [
        SystemMessage(subtype="init", data={}),
        tool_result("t1"),
        UserMessage(content="hi"),
        result(cost=9.0),
    ]
    assert [guard(m) for m in others] == [False] * len(others)
    assert guard.cost_usd == 0.0
    assert guard.messages_seen == len(others)
    assert guard.tripped is False
