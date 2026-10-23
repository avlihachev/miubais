from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["direct", "indirect-tool-result", "indirect-file", "indirect-web", "benign"]
Technique = Literal[
    "instruction-override",
    "role-play",
    "fake-system-message",
    "tool-result-injection",
    "data-exfiltration",
    "encoding-obfuscation",
    "delimiter-escape",
    "approval-spoof",
    "none",
]
SourceChannel = Literal["ticket", "file", "tool_output", "web", "user"]
Asi = Literal[
    "ASI01",
    "ASI02",
    "ASI03",
    "ASI04",
    "ASI05",
    "ASI06",
    "ASI07",
    "ASI08",
    "ASI09",
    "ASI10",
    "none",
]
AuditEventName = Literal[
    "run.start",
    "tool.call",
    "tool.denied",
    "taint.set",
    "taint.cleared",
    "secret.redacted",
    "approval",
    "run.end",
]
Actor = Literal["model", "host", "human"]
SecretKind = Literal[
    "anthropic-key",
    "langfuse-key",
    "aws-access-key",
    "github-token",
    "private-key",
    "bearer-token",
    "jwt",
    "env-secret",
]

KINDS: tuple[str, ...] = get_args(Kind)
TECHNIQUES: tuple[str, ...] = get_args(Technique)
SOURCE_CHANNELS: tuple[str, ...] = get_args(SourceChannel)
ASI_IDS: tuple[str, ...] = tuple(a for a in get_args(Asi) if a != "none")
AUDIT_EVENTS: tuple[str, ...] = get_args(AuditEventName)
ACTORS: tuple[str, ...] = get_args(Actor)
SECRET_KINDS: tuple[str, ...] = get_args(SecretKind)

ASI_TITLES: dict[str, str] = {
    "ASI01": "Agent Goal Hijack",
    "ASI02": "Tool Misuse and Exploitation",
    "ASI03": "Identity and Privilege Abuse",
    "ASI04": "Agentic Supply Chain Vulnerabilities",
    "ASI05": "Unexpected Code Execution",
    "ASI06": "Memory and Context Poisoning",
    "ASI07": "Insecure Inter-Agent Communication",
    "ASI08": "Cascading Failures",
    "ASI09": "Human-Agent Trust Exploitation",
    "ASI10": "Rogue Agents",
}

SIDE_EFFECT_TOOLS: frozenset[str] = frozenset(
    {"Edit", "MultiEdit", "Write", "Bash", "NotebookEdit"}
)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Kind
    technique: Technique
    asi: Asi
    source_channel: SourceChannel
    text: str = Field(min_length=1, max_length=600)


@dataclass(frozen=True)
class Detection:
    score: float
    technique: str
    reasons: list[str]


@dataclass(frozen=True)
class Tagged:
    text: str
    sha256: str
    source: str


@dataclass
class Taint:
    tainted: bool = False
    reason: str = ""
    since_tool_use_id: str | None = None


@dataclass(frozen=True)
class Redaction:
    text: str
    counts: dict[str, int]


@dataclass(frozen=True)
class Token:
    token: str
    audience: str
    scopes: list[str]
    expires_at: datetime


@dataclass(frozen=True)
class AuditEvent:
    ts: str
    run_id: str
    ticket_id: str
    event: AuditEventName
    actor: Actor
    payload: dict
    tool_use_id: str | None = None


@dataclass(frozen=True)
class RedTeamCase:
    id: str
    technique: str
    asi: str
    prompt: str
    canary: str
    expect_no_canary: bool = True
    expect_no_side_effect: bool = True


@dataclass(frozen=True)
class RedTeamResult:
    total: int
    blocked: int
    leaked: int
    by_technique: dict[str, dict[str, int]] = field(default_factory=dict)
