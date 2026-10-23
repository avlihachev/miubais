import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DENIED = [
    r"\brm\s+(?:[^\s;&|]+\s+)*?(?:-[a-z]*r[a-z]*|--recursive)\b",
    r"\bgit(?:\s+(?:-c\s+\S+|--(?:git-dir|work-tree|namespace)\s+\S+|--?[\w-]+(?:=\S+)?))*\s+push\b",
    r"\b(curl|wget)\b.*\|\s*(ba|z)?sh\b",
    r"\bsudo\b",
]
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}
REDIRECT = re.compile(r"(?:&>|\d?>>?)(?!&)\s*('[^']*'|\"[^\"]*\"|[^\s;&|<>()]+)")
HARMLESS_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr"}


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str


@dataclass
class Policy:
    writable: list[Path]
    denied_commands: list[str] = field(default_factory=lambda: list(DEFAULT_DENIED))
    max_file_bytes: int = 200_000
    passthrough: frozenset[str] = frozenset({"TodoWrite"})

    def decide(
        self, tool_name: str, tool_input: dict, cwd: Path, *, agent_type: str | None = None
    ) -> Decision:
        if tool_name in READ_TOOLS:
            return Decision(True, f"{tool_name} is read-only")
        if tool_name in self.passthrough:
            return Decision(True, f"{tool_name} passes through")
        if tool_name in WRITE_TOOLS:
            return self._decide_write(tool_name, tool_input, cwd)
        if tool_name == "Bash":
            return self._decide_bash(str(tool_input.get("command", "")), cwd)
        return Decision(False, f"tool {tool_name} is not allowed")

    def is_writable(self, path: str, cwd: Path) -> bool:
        target = (Path(cwd) / Path(path).expanduser()).resolve()
        return any(target.is_relative_to(Path(root).resolve()) for root in self.writable)

    def _decide_write(self, tool_name: str, tool_input: dict, cwd: Path) -> Decision:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not path:
            return Decision(False, f"{tool_name} without a file path")
        if not self.is_writable(str(path), cwd):
            return Decision(False, f"{path} is outside the writable roots")
        size = len(str(tool_input.get("content", tool_input.get("new_string", ""))).encode())
        if size > self.max_file_bytes:
            return Decision(False, f"{size} bytes exceeds max_file_bytes {self.max_file_bytes}")
        return Decision(True, f"{path} is under a writable root")

    def _decide_bash(self, command: str, cwd: Path) -> Decision:
        for pattern in self.denied_commands:
            if re.search(pattern, command, re.IGNORECASE):
                return Decision(False, f"command denied by rule {pattern!r}")
        for match in REDIRECT.finditer(command):
            target = _unquote(match.group(1))
            if target not in HARMLESS_TARGETS and not self.is_writable(target, cwd):
                return Decision(False, f"redirect to {target} is outside the writable roots")
        return Decision(True, "command allowed")


def _unquote(token: str) -> str:
    try:
        parts = shlex.split(token)
    except ValueError:
        return token
    return parts[0] if parts else token
