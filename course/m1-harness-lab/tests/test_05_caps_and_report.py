from claude_agent_sdk import UserMessage
from conftest import assistant, result, text, tool_use
from harness_lab.caps import Caps, summarise, to_markdown

CAPS = Caps(max_turns=5, max_usd=0.50)


def test_success_run():
    messages = [
        assistant(text("looking"), tool_use("t1", "Read", {"file_path": "a.py"})),
        assistant(text("fixed it")),
        result("success", turns=2, cost=0.12),
    ]
    summary = summarise(messages, CAPS)
    assert summary.stopped_by == "success"
    assert summary.turns == 2
    assert summary.cost_usd == 0.12
    assert summary.final_text == "fixed it"


def test_max_turns_run():
    messages = [assistant(text("step")) for _ in range(5)]
    messages.append(result("error_max_turns", turns=5, cost=0.2))
    summary = summarise(messages, CAPS)
    assert summary.stopped_by == "max_turns"
    assert summary.turns == 5


def test_budget_overshoot_is_budget_even_on_success_subtype():
    messages = [assistant(text("done")), result("success", turns=1, cost=0.62)]
    summary = summarise(messages, CAPS)
    assert summary.stopped_by == "budget"
    assert summary.cost_usd == 0.62


def test_budget_subtype_is_budget():
    messages = [assistant(text("x")), result("error_max_budget_usd", cost=0.4)]
    assert summarise(messages, CAPS).stopped_by == "budget"


def test_budget_beats_max_turns():
    messages = [assistant(text("x")), result("error_max_turns", turns=5, cost=0.9)]
    assert summarise(messages, CAPS).stopped_by == "budget"


def test_other_error_subtype_is_error():
    messages = [assistant(text("x")), result("error_during_execution", cost=0.01)]
    assert summarise(messages, CAPS).stopped_by == "error"


def test_reaching_the_turn_count_is_not_max_turns_without_the_subtype():
    messages = [assistant(text("x")) for _ in range(5)]
    messages.append(result("error_during_execution", turns=5, cost=0.01))
    assert summarise(messages, CAPS).stopped_by == "error"


def test_error_result_with_success_subtype_is_error():
    final = result("success", cost=0.01)
    final.is_error = True
    messages = [assistant(text("x")), final]
    assert summarise(messages, CAPS).stopped_by == "error"


def test_no_result_message_is_error():
    summary = summarise([assistant(text("half"))], CAPS)
    assert summary.stopped_by == "error"
    assert summary.cost_usd == 0.0
    assert summary.final_text == "half"


def test_missing_cost_counts_as_zero():
    summary = summarise([assistant(text("x")), result("success", cost=None)], CAPS)
    assert summary.cost_usd == 0.0
    assert summary.stopped_by == "success"


def test_final_text_is_last_assistant_text_blocks_joined():
    messages = [
        assistant(text("first")),
        assistant(text("part one"), tool_use("t", "Bash", {"command": "ls"}), text("part two")),
        result("success"),
    ]
    assert summarise(messages, CAPS).final_text == "part one\npart two"


def test_empty_messages():
    summary = summarise([], CAPS)
    assert (summary.turns, summary.final_text, summary.stopped_by) == (0, "", "error")


def test_to_markdown_has_the_report_lines():
    summary = summarise([assistant(text("all done")), result("success", cost=0.1234)], CAPS)
    lines = to_markdown(summary).splitlines()
    assert "stopped_by: success" in lines
    assert "turns: 1" in lines
    assert "cost_usd: 0.1234" in lines
    assert "all done" in lines


def test_to_markdown_says_budget():
    summary = summarise([assistant(text("x")), result("success", cost=0.9)], CAPS)
    assert "stopped_by: budget" in to_markdown(summary)


def test_success_at_turn_limit_is_success():
    messages = [assistant(text("x")) for _ in range(5)]
    messages.append(result("success", turns=5, cost=0.1))
    assert summarise(messages, CAPS).stopped_by == "success"


def test_cost_equal_to_cap_is_budget():
    messages = [assistant(text("x")), result("success", cost=0.50)]
    assert summarise(messages, CAPS).stopped_by == "budget"


def test_turns_come_from_result_num_turns():
    messages = [assistant(text("a")), assistant(text("b")), result("success", turns=9)]
    assert summarise(messages, CAPS).turns == 9


def test_without_a_result_turns_count_distinct_message_ids():
    messages = [
        assistant(text("reading"), message_id="msg_1"),
        assistant(tool_use("t1", "Read", {"file_path": "a.py"}), message_id="msg_1"),
        assistant(text("editing"), message_id="msg_2"),
    ]
    assert summarise(messages, CAPS).turns == 2


def test_without_ids_turns_fall_back_to_assistant_messages():
    assert summarise([assistant(text("a")), assistant(text("b"))], CAPS).turns == 2


def test_resumed_run_subtracts_the_previous_total():
    messages = [assistant(text("x")), result("success", cost=0.70)]
    summary = summarise(messages, CAPS, previous_cost_usd=0.45)
    assert summary.stopped_by == "success"
    assert abs(summary.cost_usd - 0.25) < 1e-9


def test_resumed_run_over_its_own_cap_is_budget():
    messages = [assistant(text("x")), result("success", cost=1.00)]
    assert summarise(messages, CAPS, previous_cost_usd=0.45).stopped_by == "budget"


def test_user_messages_are_not_turns():
    messages = [
        assistant(text("a")),
        UserMessage(content="tool output"),
        assistant(text("b")),
        UserMessage(content="more"),
        result("success"),
    ]
    summary = summarise(messages, CAPS)
    assert summary.turns == 1
    assert summary.final_text == "b"
