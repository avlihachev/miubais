import os
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Protocol

from miubais.requirements import SystemProbe

DISALLOWED_TOOLS = [
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Bash",
    "WebFetch",
    "WebSearch",
    "Agent",
]

WEB_TOOLS = {"WebFetch", "WebSearch"}
PATH_TOOLS = "Read|Grep|Glob"
GLOB_CHARS = set("*?[{")


@dataclass(frozen=True)
class ModelRequest:
    system: str
    prompt: str
    cwd: Path
    allowed_tools: list[str]
    max_turns: int = 3
    schema: dict | None = None
    model: str | None = None
    allow_web: bool = False
    allowed_paths: list[Path] | None = None


@dataclass(frozen=True)
class ModelResult:
    text: str
    structured: dict | None
    cost_usd: float
    session_id: str | None
    model: str | None = None


class ModelError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        subtype: str | None = None,
        cost_usd: float = 0.0,
        session_id: str | None = None,
    ):
        super().__init__(message)
        self.subtype = subtype
        self.cost_usd = cost_usd
        self.session_id = session_id


class ModelClient(Protocol):
    async def complete(self, req: ModelRequest) -> ModelResult: ...


class FakeModelClient:
    def __init__(self, responses: list[ModelResult | Exception]):
        self.responses = list(responses)
        self.requests: list[ModelRequest] = []

    async def complete(self, req: ModelRequest) -> ModelResult:
        self.requests.append(req)
        assert self.responses, "FakeModelClient: no responses left"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


Guard = Callable[[dict, str | None, Any], Awaitable[dict]]


def _static_prefix(pattern: str) -> str:
    parts = []
    for part in Path(pattern).parts:
        if GLOB_CHARS & set(part):
            break
        parts.append(part)
    return str(Path(*parts)) if parts else "."


def _requested_paths(tool: str, tool_input: dict) -> list[str]:
    if tool == "Read":
        return [tool_input.get("file_path", "")]
    base = tool_input.get("path") or "."
    paths = [base]
    if tool == "Glob":
        paths.append(str(Path(base) / _static_prefix(tool_input.get("pattern", ""))))
    if tool_input.get("glob"):
        paths.append(str(Path(base) / _static_prefix(tool_input["glob"])))
    return paths


def path_guard(allowed: list[Path], cwd: Path, denied: list[str] | None = None) -> Guard:
    roots = [p.resolve() for p in allowed]

    def inside(raw: str) -> bool:
        path = (cwd / raw).resolve()
        return any(path == root or path.is_relative_to(root) for root in roots)

    async def guard(input_data: dict, tool_use_id: str | None, context: Any) -> dict:
        tool = input_data.get("tool_name", "")
        outside = [
            p for p in _requested_paths(tool, input_data.get("tool_input", {})) if not inside(p)
        ]
        if not outside:
            return {}
        if denied is not None:
            denied.append(f"{tool} {outside[0]}")
        return {
            "hookSpecificOutput": {
                "hookEventName": input_data.get("hook_event_name", "PreToolUse"),
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{outside[0]} is outside the paths the tutor may read",
            }
        }

    return guard


def default_model() -> str:
    return os.environ.get("MIUBAIS_MODEL", "claude-opus-5-5")


class AgentSdkClient:
    def __init__(self, model: str | None = None):
        self.model = model or default_model()
        self.denied: list[str] = []

    async def complete(self, req: ModelRequest) -> ModelResult:
        try:
            return await self._complete(req)
        except ModelError:
            raise
        except Exception as err:
            raise ModelError(f"model call failed: {type(err).__name__}: {err}") from err

    async def _complete(self, req: ModelRequest) -> ModelResult:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            HookMatcher,
            ResultMessage,
            TextBlock,
            query,
        )

        hooks = None
        if req.allowed_paths is not None:
            guard = path_guard(req.allowed_paths, req.cwd, self.denied)
            hooks = {"PreToolUse": [HookMatcher(matcher=PATH_TOOLS, hooks=[guard])]}

        options = ClaudeAgentOptions(
            system_prompt=req.system,
            allowed_tools=req.allowed_tools,
            disallowed_tools=[
                t for t in DISALLOWED_TOOLS if not (req.allow_web and t in WEB_TOOLS)
            ],
            permission_mode="dontAsk",
            max_turns=req.max_turns,
            cwd=req.cwd,
            setting_sources=[],
            model=req.model or self.model,
            output_format={"type": "json_schema", "schema": req.schema} if req.schema else None,
            hooks=hooks,
        )
        texts: list[str] = []
        model = None
        final: ResultMessage | None = None
        async with aclosing(query(prompt=req.prompt, options=options)) as stream:
            async for message in stream:
                if isinstance(message, AssistantMessage):
                    texts.extend(b.text for b in message.content if isinstance(b, TextBlock))
                    model = message.model or model
                elif isinstance(message, ResultMessage):
                    final = message
        if final is None:
            raise ModelError("model run ended without a result message")
        cost = final.total_cost_usd or 0.0
        if final.is_error or final.subtype != "success":
            detail = "; ".join(final.errors or []) or final.result or ""
            raise ModelError(
                f"model run failed ({final.subtype}) {detail}".strip(),
                subtype=final.subtype,
                cost_usd=cost,
                session_id=final.session_id,
            )
        if req.schema and final.structured_output is None:
            raise ModelError(
                "no structured output returned for requested schema",
                subtype=final.subtype,
                cost_usd=cost,
                session_id=final.session_id,
            )
        return ModelResult(
            text="\n".join(texts),
            structured=final.structured_output,
            cost_usd=cost,
            session_id=final.session_id,
            model=model or req.model or self.model,
        )


def default_client() -> ModelClient:
    return AgentSdkClient()


@cache
def claude_available() -> bool:
    return SystemProbe().has("claude-auth")
