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
from harnesskit.report import to_markdown
from harnesskit.runner import TicketDone, run_ticket
from harnesskit.sessions import SessionStore
from harnesskit.testing import scripted_query
from harnesskit.traces import to_trace_lines


def result(
    subtype="success", session_id="sess-new", cost=0.05, turns=3, is_error=None
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=10,
        duration_api_ms=8,
        is_error=subtype != "success" if is_error is None else is_error,
        num_turns=turns,
        session_id=session_id,
        total_cost_usd=cost,
    )


def said(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextBlock(text=text)], model="claude-opus-5-5")


class Scripted:
    def __init__(self, *runs):
        self.runs = list(runs)
        self.calls: list[tuple[str, object]] = []

    def __call__(self, prompt, options):
        self.calls.append((prompt, options))
        run = self.runs.pop(0)
        return scripted_query([run] if isinstance(run, Exception) else run)(prompt, options)


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
def store(tmp_path: Path):
    with SessionStore(tmp_path / "sessions.db") as s:
        yield s


@pytest.fixture
def policy(repo: Path) -> Policy:
    return Policy(writable=[repo / "src"])


def edit_file(repo: Path):
    async def step(options):
        (repo / "src" / "a.py").write_text("x = 2\n")
        (repo / "src" / "new.py").write_text("y = 1\n")

    return step


def test_success_run(repo, ticket, store, policy):
    fn = Scripted([said("on it"), edit_file(repo), result()])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn, model="claude-opus-5-5")
    assert (r.ticket_id, r.session_id, r.turns, r.stopped_by) == (
        "001-discount-rounding",
        "sess-new",
        3,
        "success",
    )
    assert r.cost_usd == pytest.approx(0.05)
    assert sorted(r.files_changed) == ["src/a.py", "src/new.py"]
    assert r.resumed is False and r.notes == []
    assert store.get("001-discount-rounding").session_id == "sess-new"
    assert store.get("001-discount-rounding").status == "done"


def test_options(repo, ticket, store, policy):
    fn = Scripted([result()])
    agents = {"reviewer": object()}
    run_ticket(
        ticket,
        repo,
        policy=policy,
        store=store,
        max_turns=5,
        max_budget_usd=0.2,
        model="m",
        agents=agents,
        query_fn=fn,
    )
    prompt, options = fn.calls[0]
    assert "Fix it." in prompt
    assert options.cwd == repo
    assert options.allowed_tools == ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "Agent"]
    assert options.permission_mode == "dontAsk"
    assert options.max_turns == 5 and options.max_budget_usd == 0.2
    assert options.resume is None and options.setting_sources == []
    assert options.model == "m" and options.agents is agents
    assert options.system_prompt
    assert len(options.hooks["PreToolUse"]) == 1


def test_hook_in_options_enforces_policy(repo, ticket, store, policy):
    import asyncio

    fn = Scripted([result()])
    run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    hook = fn.calls[0][1].hooks["PreToolUse"][0].hooks[0]
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": str(repo),
        "tool_name": "Bash",
        "tool_input": {"command": "git push"},
    }
    out = asyncio.run(hook(event, "t1", None))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_resumes_stored_session(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-old")
    fn = Scripted([said("back"), result(session_id="sess-old")])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert fn.calls[0][1].resume == "sess-old"
    assert r.resumed is True and r.notes == []


def test_resume_raises_falls_back_to_fresh(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-stale")
    fn = Scripted(RuntimeError("No conversation found"), [said("fresh"), result()])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert [c[1].resume for c in fn.calls] == ["sess-stale", None]
    assert r.resumed is False
    assert r.notes == ["resume failed: No conversation found; started fresh"]
    assert r.session_id == "sess-new" and r.stopped_by == "success"
    assert store.get("001-discount-rounding").session_id == "sess-new"


def test_resume_error_result_falls_back_to_fresh(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-stale")
    fn = Scripted([result("error_during_execution", session_id="x")], [result()])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert len(fn.calls) == 2 and r.resumed is False
    assert r.notes == ["resume failed: error_during_execution; started fresh"]


def test_error_after_assistant_is_not_a_resume_failure(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-old")
    fn = Scripted([said("working"), result("error_max_turns", session_id="sess-old")])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert len(fn.calls) == 1
    assert r.resumed is True and r.stopped_by == "max_turns"
    assert store.get("001-discount-rounding").status == "open"


def test_budget_overshoot_reports_budget(repo, ticket, store, policy):
    fn = Scripted([said("done"), result("success", cost=0.61)])
    r = run_ticket(ticket, repo, policy=policy, store=store, max_budget_usd=0.5, query_fn=fn)
    assert r.stopped_by == "budget"


def test_budget_subtype_reports_budget(repo, ticket, store, policy):
    fn = Scripted([said("x"), result("error_max_budget_usd", cost=None)])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.stopped_by == "budget" and r.cost_usd == 0.0


def deny_push(options):
    async def step(_):
        hook = options.hooks["PreToolUse"][0].hooks[0]
        event = {
            "hook_event_name": "PreToolUse",
            "cwd": str(options.cwd),
            "tool_name": "Bash",
            "tool_input": {"command": "git push"},
        }
        await hook(event, "t1", None)

    return step


class Denying(Scripted):
    def __call__(self, prompt, options):
        self.runs[0] = [deny_push(options) if item == "DENY" else item for item in self.runs[0]]
        return super().__call__(prompt, options)


def test_denial_that_ends_in_error_is_policy(repo, ticket, store, policy):
    run = [said("pushing"), ToolUseBlock(id="t1", name="Bash", input={}), "DENY"]
    fn = Denying(run + [result("error_during_execution")])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.stopped_by == "policy"


def test_denial_then_success_is_success(repo, ticket, store, policy):
    fn = Denying([said("pushing"), "DENY", result()])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.stopped_by == "success"


def test_fresh_run_that_raises_reports_error(repo, ticket, store, policy):
    fn = Scripted(RuntimeError("cli missing"))
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.stopped_by == "error" and r.notes == ["run failed: cli missing"]
    assert store.get("001-discount-rounding") is None


def test_files_changed_empty_outside_git(tmp_path, ticket, store):
    plain = tmp_path / "plain"
    plain.mkdir()
    fn = Scripted([result()])
    r = run_ticket(ticket, plain, policy=Policy(writable=[plain]), store=store, query_fn=fn)
    assert r.files_changed == []


def test_fresh_budget_stop_is_reported_not_raised(repo, ticket, store, policy):
    fn = Scripted([said("reading"), result("error_max_budget_usd", cost=0.52)])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert (r.stopped_by, r.session_id, r.notes) == ("budget", "sess-new", [])
    assert len(fn.calls) == 1


def test_resumed_max_turns_after_output_is_not_rerun(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-old")
    fn = Scripted([said("working"), result("error_max_turns", session_id="sess-old")], [result()])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert len(fn.calls) == 1
    assert (r.resumed, r.stopped_by, r.notes) == (True, "max_turns", [])


def test_error_during_execution_is_error(repo, ticket, store, policy):
    fn = Scripted([said("x"), result("error_during_execution")])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.stopped_by == "error" and r.notes == []


def test_failed_final_request_is_error_and_stays_open(repo, ticket, store, policy):
    fn = Scripted([said("x"), result(is_error=True)])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.stopped_by == "error"
    assert store.get("001-discount-rounding").status == "open"


def test_turns_come_from_num_turns(repo, ticket, store, policy):
    fn = Scripted([said("a"), said("b"), result(turns=7)])
    assert run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn).turns == 7


def test_turns_without_a_result_count_distinct_message_ids(repo, ticket, store, policy):
    first = AssistantMessage(content=[TextBlock(text="a")], model="m", message_id="msg_1")
    second = AssistantMessage(content=[TextBlock(text="b")], model="m", message_id="msg_1")
    third = AssistantMessage(content=[TextBlock(text="c")], model="m", message_id="msg_2")
    fn = Scripted([first, second, third, RuntimeError("connection lost")])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert (r.stopped_by, r.turns) == ("error", 2)


def test_resumed_run_subtracts_the_stored_total(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-old", cost_usd=0.45)
    fn = Scripted([said("finishing"), result(session_id="sess-old", cost=0.70)])
    r = run_ticket(ticket, repo, policy=policy, store=store, max_budget_usd=0.5, query_fn=fn)
    assert r.stopped_by == "success" and r.cost_usd == pytest.approx(0.25)
    assert store.get("001-discount-rounding").cost_usd == pytest.approx(0.70)


def test_resumed_run_over_its_own_budget_is_budget(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-old", cost_usd=0.45)
    fn = Scripted([said("x"), result(session_id="sess-old", cost=1.00)])
    r = run_ticket(ticket, repo, policy=policy, store=store, max_budget_usd=0.5, query_fn=fn)
    assert r.stopped_by == "budget"


def test_fresh_fallback_ignores_the_stale_total(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-stale", cost_usd=0.45)
    fn = Scripted([result("error_during_execution", session_id="x")], [said("y"), result()])
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert r.resumed is False and r.cost_usd == pytest.approx(0.05)


def test_agents_let_the_agent_tool_through(repo, ticket, store, policy):
    import asyncio

    fn = Scripted([result()], [result()])
    run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    store.mark("001-discount-rounding", "open")
    run_ticket(ticket, repo, policy=policy, store=store, agents={"reviewer": object()}, query_fn=fn)
    plain, with_agents = (call[1] for call in fn.calls)
    assert "Agent" not in plain.allowed_tools and "Agent" in with_agents.allowed_tools
    event = {"hook_event_name": "PreToolUse", "cwd": str(repo), "tool_name": "Agent"}
    event["tool_input"] = {"subagent_type": "reviewer", "prompt": "review"}
    deny = asyncio.run(plain.hooks["PreToolUse"][0].hooks[0](event, "t1", None))
    allow = asyncio.run(with_agents.hooks["PreToolUse"][0].hooks[0](event, "t1", None))
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny" and allow == {}
    assert "Agent" not in policy.passthrough


def test_done_ticket_is_not_run_again(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-done", status="done", cost_usd=0.2)
    fn = Scripted([result()])
    with pytest.raises(TicketDone, match="001-discount-rounding"):
        run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert fn.calls == []
    assert store.get("001-discount-rounding").session_id == "sess-done"


def tool_round() -> list:
    return [
        AssistantMessage(
            content=[ToolUseBlock(id="t1", name="Read", input={"file_path": "a.py"})],
            model="claude-opus-5-5",
            message_id="m1",
            session_id="sess-obs",
        ),
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="x = 1")]),
    ]


def test_observer_sees_every_message_in_order(repo, ticket, store, policy):
    script = [*tool_round(), said("done"), result()]
    seen = []
    run_ticket(
        ticket,
        repo,
        policy=policy,
        store=store,
        query_fn=Scripted(script),
        observer=seen.append,
    )
    assert seen == script
    assert [type(m) for m in seen][1] is UserMessage


def test_report_keeps_messages_out_of_markdown_and_dump(repo, ticket, store, policy):
    script = [*tool_round(), result()]
    r = run_ticket(ticket, repo, policy=policy, store=store, query_fn=Scripted(script))
    assert r.messages == script
    assert "messages" not in r.model_dump()
    assert "x = 1" not in to_markdown(r)
    lines = to_trace_lines(r.messages)
    assert [line.role for line in lines] == ["assistant", "tool", "result"]
    assert lines[1].tool == "Read" and lines[1].output == "x = 1"


class Stopper:
    def __init__(self, after: int):
        self.after, self.n, self.cost_usd = after, 0, 0.42

    def __call__(self, message) -> bool:
        self.n += 1
        return self.n >= self.after


def test_observer_stop_ends_before_the_result(repo, ticket, store, policy):
    script = [*tool_round(), said("never"), result()]
    stopper = Stopper(2)
    r = run_ticket(
        ticket, repo, policy=policy, store=store, query_fn=Scripted(script), observer=stopper
    )
    assert stopper.n == 2
    assert r.stopped_by == "budget" and r.cost_usd == 0.42
    assert r.notes == ["stopped by observer"]
    assert r.session_id == "sess-obs" and r.turns == 1
    assert r.messages == script[:2]
    assert store.get("001-discount-rounding") is None


def test_observer_stop_without_cost_attribute_reports_zero(repo, ticket, store, policy):
    r = run_ticket(
        ticket,
        repo,
        policy=policy,
        store=store,
        query_fn=Scripted([said("a"), result()]),
        observer=lambda m: True,
    )
    assert r.cost_usd == 0.0 and r.session_id is None


def test_observer_error_propagates_and_is_not_a_resume_failure(repo, ticket, store, policy):
    store.put("001-discount-rounding", "sess-old")
    init = SystemMessage(subtype="init", data={})
    fn = Scripted([init, said("a"), result()], [init, said("b"), result()])

    def broken(message):
        raise ValueError("observer broke")

    with pytest.raises(ValueError, match="observer broke"):
        run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn, observer=broken)
    assert len(fn.calls) == 1


def test_post_tool_use_registered_when_given(repo, ticket, store, policy):
    import asyncio

    async def hook(input_data, tool_use_id, context):
        return {"seen": input_data["tool_name"]}

    fn = Scripted([result()])
    run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn, post_tool_use=hook)
    options = fn.calls[0][1]
    assert len(options.hooks["PreToolUse"]) == 1
    registered = options.hooks["PostToolUse"][0]
    assert registered.matcher is None and registered.hooks == [hook]
    assert asyncio.run(registered.hooks[0]({"tool_name": "Bash"}, "t1", None)) == {"seen": "Bash"}


def test_post_tool_use_absent_by_default(repo, ticket, store, policy):
    fn = Scripted([result()])
    run_ticket(ticket, repo, policy=policy, store=store, query_fn=fn)
    assert "PostToolUse" not in fn.calls[0][1].hooks


def test_extra_hooks_run_alongside_policy_hook(repo, ticket, store, policy):
    seen: list[str] = []

    async def taint(input_data, tool_use_id, context):
        seen.append(input_data["tool_name"])
        return {"hookSpecificOutput": {"permissionDecision": "deny"}}

    async def post(input_data, tool_use_id, context):
        return {}

    async def fire(options):
        for matcher in options.hooks["PreToolUse"]:
            for hook in matcher.hooks:
                outputs.append(await hook({"tool_name": "Read", "tool_input": {}}, "t1", None))

    outputs: list[dict] = []
    fn = Scripted([fire, result()])
    run_ticket(
        ticket,
        repo,
        policy=policy,
        store=store,
        query_fn=fn,
        post_tool_use=post,
        extra_hooks={"PreToolUse": [taint], "PostToolUse": [post], "Stop": []},
    )
    options = fn.calls[0][1]
    pre = options.hooks["PreToolUse"]
    assert len(pre) == 2 and pre[1].hooks == [taint] and pre[1].matcher is None
    assert [m.hooks for m in options.hooks["PostToolUse"]] == [[post], [post]]
    assert "Stop" not in options.hooks
    assert seen == ["Read"] and outputs[0] == {} and "deny" in str(outputs[1])
