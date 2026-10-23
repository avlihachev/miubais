from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from harnesskit.policy import Policy

HookCallback = Callable[[dict, str | None, Any], Awaitable[dict]]


def deny(event_name: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def allow() -> dict:
    return {}


def pre_tool_use(policy: Policy, *, audit: Callable[[dict], None] | None = None) -> HookCallback:
    async def callback(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        event = input_data.get("hook_event_name", "PreToolUse")
        if event != "PreToolUse":
            return allow()
        try:
            tool_name = input_data["tool_name"]
            cwd = Path(input_data.get("cwd") or Path.cwd())
            decision = policy.decide(
                tool_name,
                input_data.get("tool_input") or {},
                cwd,
                agent_type=input_data.get("agent_type"),
            )
            if audit is not None:
                audit(
                    {
                        "tool_name": tool_name,
                        "tool_use_id": tool_use_id,
                        "allow": decision.allow,
                        "reason": decision.reason,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - fail closed, never let the tool through
            return deny(event, f"policy error: {type(exc).__name__}: {exc}")
        return allow() if decision.allow else deny(event, decision.reason)

    return callback


def post_tool_use(
    transform: Callable[[dict], Any | None],
    *,
    on_error: Callable[[Exception], None] | None = None,
) -> HookCallback:
    async def callback(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        event = input_data.get("hook_event_name", "PostToolUse")
        if event != "PostToolUse":
            return allow()
        try:
            replacement = transform(input_data)
        except Exception as exc:  # noqa: BLE001
            if on_error is not None:
                on_error(exc)
            return allow()
        if replacement is None:
            return allow()
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "updatedToolOutput": replacement,
            }
        }

    return callback
