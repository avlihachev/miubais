from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from harness_lab_lessons import summarise_messages

PARENT, REVIEWER = "claude-opus-5-5", "claude-sonnet-5-5"

messages = [
    AssistantMessage(
        [ToolUseBlock("toolu_01", "Edit", {"file_path": "/work/tinyshop/tests/test_pricing.py"})],
        model=PARENT,
    ),
    AssistantMessage(
        [ToolUseBlock("toolu_02", "Agent", {"subagent_type": "diff-reviewer", "prompt": "Review"})],
        model=PARENT,
    ),
    AssistantMessage([TextBlock("The reviewer found one problem.")], model=PARENT),
    ResultMessage(
        subtype="success",
        duration_ms=41_000,
        duration_api_ms=37_500,
        is_error=False,
        num_turns=3,
        session_id="11111111-2222-4333-8444-555555555555",
        total_cost_usd=0.1840,
        usage={"input_tokens": 9_200, "output_tokens": 1_100},
        model_usage={
            PARENT: {"inputTokens": 9_200, "outputTokens": 1_100, "costUSD": 0.1210},
            REVIEWER: {"inputTokens": 21_000, "outputTokens": 800, "costUSD": 0.0630},
        },
        permission_denials=[
            {
                "tool_name": "Edit",
                "tool_use_id": "toolu_01",
                "tool_input": {"file_path": "/work/tinyshop/tests/test_pricing.py"},
            }
        ],
        structured_output={
            "approve": False,
            "findings": [
                {
                    "file": "src/tinyshop/pricing.py",
                    "line": 14,
                    "severity": "important",
                    "note": "rounding mode changed but the cart total still uses round()",
                }
            ],
        },
        terminal_reason="completed",
    ),
]

facts = summarise_messages(messages, max_turns=12, max_usd=0.30)
result = messages[-1]
print(f"stopped_by={facts.stopped_by} turns={facts.turns} cost=${facts.cost_usd:.4f}")
for model, usd in facts.cost_by_model.items():
    print(f"  {model:<18} ${usd:.4f}  {usd / facts.cost_usd:.0%}")
print("main-loop input tokens in usage:", result.usage["input_tokens"])
print("denials:", facts.denials, [d["tool_input"]["file_path"] for d in result.permission_denials])
verdict = result.structured_output
print("approve:", verdict["approve"], "findings:", [f["severity"] for f in verdict["findings"]])
