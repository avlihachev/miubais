from collections import Counter

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from harness_lab_lessons import TicketMetrics, metrics_table, summarise_messages

MAX_TURNS, MAX_USD = 12, 0.75
SESSION = "11111111-2222-4333-8444-555555555555"


def run(assistant_turns: int, subtype: str, cost: float, denied: int) -> list:
    messages = [
        AssistantMessage([ToolUseBlock(f"toolu_{i:02}", "Read", {"file_path": "x.py"})], model="m")
        for i in range(assistant_turns - 1)
    ]
    messages.append(AssistantMessage([TextBlock("Done.")], model="m"))
    denials = [{"tool_name": "Edit", "tool_use_id": "toolu_00", "tool_input": {}}] * denied
    messages.append(
        ResultMessage(
            subtype=subtype,
            duration_ms=60_000,
            duration_api_ms=55_000,
            is_error=subtype != "success",
            num_turns=assistant_turns,
            session_id=SESSION,
            total_cost_usd=cost,
            permission_denials=denials,
            terminal_reason="completed" if subtype == "success" else None,
        )
    )
    return messages


tickets = [
    ("001-discount-rounding", run(8, "success", 0.21, 0), 1, True),
    ("002-negative-quantity", run(12, "error_max_turns", 0.48, 3), 2, False),
    ("003-out-of-stock-msg", run(10, "error_max_budget_usd", 0.79, 0), 0, None),
]
rows = [
    TicketMetrics(name, summarise_messages(messages, MAX_TURNS, MAX_USD), files, tests)
    for name, messages, files, tests in tickets
]
print(metrics_table(rows))
print("stopped_by:", dict(Counter(row.facts.stopped_by for row in rows)))
spent = sum(row.facts.cost_usd for row in rows)
shipped = sum(row.facts.stopped_by == "success" and row.tests_passed is True for row in rows)
print(f"spend ${spent:.2f}, shipped {shipped}, cost per shipped ticket ${spent / shipped:.2f}")
over = [row.ticket for row in rows if row.facts.cost_usd > MAX_USD]
print("over the cap:", over)
