import hashlib
import json
import re

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, ToolUseBlock
from conftest import LAB
from harnesskit.policy import Policy
from harnesskit.runner import run_ticket
from harnesskit.sessions import SessionStore
from harnesskit.testing import scripted_query
from injection_lab import audit
from injection_lab.provenance import DENY_REASON, Taint, taint_policy
from injection_lab.types import AuditEvent, Detection

SECRET = "sk-ant-api03-" + "Q" * 24
HOSTILE = Detection(0.9, "instruction-override", ["test"])
FIELDS = {
    "ts",
    "run_id",
    "ticket_id",
    "event",
    "actor",
    "payload",
    "tool_use_id",
    "prev_sha256",
    "sha256",
}
ITEMS = [
    "run-start-end",
    "denied-has-reason",
    "taint-resolved",
    "no-secrets",
    "chain-verifies",
    "timestamps-monotonic",
    "actor-present",
    "ticket-id-present",
    "tool-use-id",
    "append-only",
]


def assistant(*blocks):
    return AssistantMessage(content=list(blocks), model="claude-opus-5-5", message_id="m1")


def result():
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=2,
        session_id="sess-1",
        total_cost_usd=0.01,
    )


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def event(name, **overrides):
    base = {
        "ts": "2026-10-17T10:00:00.000000+00:00",
        "run_id": "run-1",
        "ticket_id": "001",
        "event": name,
        "actor": "host",
        "payload": {},
        "tool_use_id": None,
    }
    return AuditEvent(**{**base, **overrides})


def forge(path, records):
    prev, out = audit.GENESIS, []
    for i, overrides in enumerate(records):
        record = {
            "ts": f"2026-10-17T10:00:{i:02d}.000000+00:00",
            "run_id": "run-1",
            "ticket_id": "001",
            "actor": "host",
            "payload": {},
            "tool_use_id": None,
            **overrides,
            "prev_sha256": prev,
        }
        record["sha256"] = audit.digest(record)
        prev = record["sha256"]
        out.append(json.dumps(record))
    path.write_text("".join(f"{line}\n" for line in out))
    return prev


GOOD = [
    {"event": "run.start"},
    {"event": "tool.call", "actor": "model", "payload": {"tool": "Read"}, "tool_use_id": "tu-1"},
    {"event": "taint.set", "payload": {"reason": "x"}, "tool_use_id": "tu-1"},
    {
        "event": "tool.denied",
        "payload": {"tool": "Bash", "reason": DENY_REASON},
        "tool_use_id": "tu-2",
    },
    {"event": "approval", "actor": "human", "payload": {"action": "taint.clear"}},
    {"event": "taint.cleared", "payload": {"reason": "x"}},
    {"event": "run.end", "payload": {"subtype": "success"}},
]


def verdicts(path, head=None):
    return {c.item: c.ok for c in audit.checklist(path, head=head)}


@pytest.fixture
def hardened_run(tmp_path, tinyshop):
    repo = tinyshop()
    log = audit.AuditLog(tmp_path / "audit.jsonl")
    observe = audit.observer(log, "run-1", "001")
    taint = audit.watch_taint(log, Taint())
    gate = taint_policy(
        taint, readonly_allow=frozenset({"mcp__shop__ticket_lookup"}), audit=audit.on_denied(log)
    )
    outputs = []

    async def hijacked(options):
        taint.mark(HOSTILE, "tu-1")
        bash = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi > src/tinyshop/x.txt"},
            "cwd": str(repo),
        }
        for matcher in options.hooks["PreToolUse"]:
            for hook in matcher.hooks:
                outputs.append(await hook(bash, "tu-2", None))

    script = [
        assistant(
            ToolUseBlock(id="tu-1", name="Read", input={"file_path": "tickets/001.md"}),
            ToolUseBlock(id="tu-2", name="Bash", input={"command": f"echo {SECRET}"}),
        ),
        hijacked,
        result(),
    ]
    with SessionStore(tmp_path / "sessions.db") as store:
        run_ticket(
            repo / "tickets" / "001-discount-rounding.md",
            repo,
            policy=Policy(writable=[repo]),
            store=store,
            query_fn=scripted_query(script),
            observer=observe,
            extra_hooks={"PreToolUse": [gate]},
        )
    return log, outputs


def test_lines_carry_the_exact_fields_and_a_chain(tmp_path):
    log = audit.AuditLog(tmp_path / "a.jsonl")
    first = log.append(event("run.start"))
    second = log.append(event("run.end"))
    records = lines(tmp_path / "a.jsonl")
    assert all(set(r) == FIELDS for r in records)
    assert records[0]["prev_sha256"] == "0" * 64
    assert [r["sha256"] for r in records] == [first, second]
    assert records[1]["prev_sha256"] == first
    without = {k: v for k, v in records[0].items() if k != "sha256"}
    canonical = json.dumps(without, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canonical.encode()).hexdigest() == first
    assert audit.verify(tmp_path / "a.jsonl") == audit.Verification(True, None, "ok")


def test_reopening_continues_the_chain(tmp_path):
    path = tmp_path / "a.jsonl"
    head = audit.AuditLog(path).append(event("run.start"))
    audit.AuditLog(path).append(event("run.end"))
    assert lines(path)[1]["prev_sha256"] == head and audit.verify(path).ok


@pytest.mark.parametrize("victim", [1, 3, 5])
def test_an_edited_line_fails_with_its_number(tmp_path, victim):
    path = tmp_path / "a.jsonl"
    forge(path, GOOD)
    rows = path.read_text().splitlines()
    record = json.loads(rows[victim - 1])
    record["payload"] = {"tool": "Write"}
    rows[victim - 1] = json.dumps(record)
    path.write_text("\n".join(rows) + "\n")
    check = audit.verify(path)
    assert not check.ok and check.line == victim and "edited" in check.reason


@pytest.mark.parametrize("victim", [2, 4, 6])
def test_a_deleted_line_fails_with_its_number(tmp_path, victim):
    path = tmp_path / "a.jsonl"
    forge(path, GOOD)
    rows = path.read_text().splitlines()
    del rows[victim - 1]
    path.write_text("\n".join(rows) + "\n")
    check = audit.verify(path)
    assert not check.ok and check.line == victim and "deleted" in check.reason


def test_truncation_is_detected(tmp_path):
    path = tmp_path / "a.jsonl"
    head = forge(path, GOOD)
    assert audit.verify(path, head=head).ok
    rows = path.read_text().splitlines()
    path.write_text("\n".join(rows[:-1]) + "\n")
    assert audit.verify(path).ok
    check = audit.verify(path, head=head)
    assert not check.ok and check.line == len(GOOD) and "truncated" in check.reason
    assert verdicts(path)["append-only"] is False
    path.write_text("\n".join(rows)[:-10])
    cut = audit.verify(path)
    assert not cut.ok and cut.line == len(GOOD) and "cut off" in cut.reason


def test_observer_logs_start_tool_calls_and_end(hardened_run):
    log, _ = hardened_run
    records = lines(log.path)
    events = [r["event"] for r in records]
    assert events.count("run.start") == 1 and events[0] == "run.start"
    assert events[-1] == "run.end" and events.count("run.end") == 1
    calls = [r for r in records if r["event"] == "tool.call"]
    assert [(c["payload"]["tool"], c["tool_use_id"]) for c in calls] == [
        ("Read", "tu-1"),
        ("Bash", "tu-2"),
    ]
    assert all(c["actor"] == "model" for c in calls)
    assert {r["run_id"] for r in records} == {"run-1"} and {r["ticket_id"] for r in records} == {
        "001"
    }


def test_tainted_bash_inside_writable_roots_is_denied_and_logged(hardened_run):
    log, outputs = hardened_run
    assert outputs[0] == {}
    assert outputs[1]["hookSpecificOutput"]["permissionDecision"] == "deny"
    denied = [r for r in lines(log.path) if r["event"] == "tool.denied"]
    assert len(denied) == 1
    assert denied[0]["payload"] == {"tool": "Bash", "reason": DENY_REASON}
    assert denied[0]["tool_use_id"] == "tu-2" and denied[0]["actor"] == "host"
    taint_set = [r for r in lines(log.path) if r["event"] == "taint.set"]
    assert len(taint_set) == 1 and taint_set[0]["tool_use_id"] == "tu-1"


def test_on_denied_ignores_allowed_calls(tmp_path):
    log = audit.AuditLog(tmp_path / "a.jsonl")
    log.current = ("run-1", "001")
    callback = audit.on_denied(log)
    callback({"tool_name": "Read", "tool_use_id": "t", "allow": True, "reason": "ok"})
    assert not (tmp_path / "a.jsonl").exists() or lines(tmp_path / "a.jsonl") == []
    with pytest.raises(RuntimeError):
        audit.on_denied(audit.AuditLog(tmp_path / "b.jsonl"))(
            {"tool_name": "Bash", "allow": False, "reason": "r"}
        )


def test_payload_secrets_are_scrubbed_and_counted(hardened_run):
    log, _ = hardened_run
    text = log.path.read_text()
    assert SECRET not in text and "[REDACTED:anthropic-key]" in text
    redacted = [r for r in lines(log.path) if r["event"] == "secret.redacted"]
    assert len(redacted) == 1
    assert redacted[0]["payload"] == {"of": "tool.call", "counts": {"anthropic-key": 1}}
    assert redacted[0]["tool_use_id"] == "tu-2"


def test_taint_clear_logs_approval_without_the_id(tmp_path):
    log = audit.AuditLog(tmp_path / "a.jsonl")
    log.current = ("run-1", "001")
    taint = audit.watch_taint(log, Taint())
    taint.mark(HOSTILE, "tu-1")
    approval_id = taint.mint_approval()
    taint.clear(approval_id)
    records = lines(tmp_path / "a.jsonl")
    assert [r["event"] for r in records] == ["taint.set", "approval", "taint.cleared"]
    assert records[1]["actor"] == "human"
    assert approval_id not in (tmp_path / "a.jsonl").read_text()


def test_timestamps_never_go_backwards(tmp_path):
    log = audit.AuditLog(tmp_path / "a.jsonl")
    log.append(event("run.start", ts="2026-10-17T10:00:05.000000+00:00"))
    log.append(event("run.end", ts="2026-10-17T10:00:01.000000+00:00"))
    stamps = [r["ts"] for r in lines(tmp_path / "a.jsonl")]
    assert stamps == sorted(stamps)


def test_checklist_passes_on_a_hardened_run(hardened_run):
    log, _ = hardened_run
    checks = audit.checklist(log.path, head=log.head)
    assert [c.item for c in checks] == ITEMS
    assert all(c.satisfied_by for c in checks)
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_checklist_document_lists_the_ten_items():
    text = (LAB / "CHECKLIST.md").read_text()
    rows = re.findall(r"^\| (\d+) \| `([a-z-]+)`", text, flags=re.MULTILINE)
    assert [item for _, item in rows] == ITEMS
    assert [int(n) for n, _ in rows] == list(range(1, 11))
    assert text.count("Art. ") >= 10


def test_forged_good_log_passes_every_item(tmp_path):
    path = tmp_path / "a.jsonl"
    head = forge(path, GOOD)
    assert all(verdicts(path, head).values())


NEGATIVE = {
    "run-start-end": GOOD[:-1] + [{"event": "tool.call", "tool_use_id": "t9"}],
    "denied-has-reason": [
        r if r["event"] != "tool.denied" else {**r, "payload": {"tool": "Bash", "reason": " "}}
        for r in GOOD
    ],
    "taint-resolved": [r for r in GOOD if r["event"] != "approval"],
    "no-secrets": [
        GOOD[0],
        {"event": "tool.call", "payload": {"input": f"key {SECRET}"}, "tool_use_id": "t1"},
        GOOD[-1],
    ],
    "timestamps-monotonic": [
        GOOD[0],
        {**GOOD[1], "ts": "2026-10-17T09:00:00.000000+00:00"},
        GOOD[-1],
    ],
    "actor-present": [GOOD[0], {**GOOD[1], "actor": "robot"}, GOOD[-1]],
    "ticket-id-present": [GOOD[0], {**GOOD[1], "ticket_id": ""}, GOOD[-1]],
    "tool-use-id": [GOOD[0], {**GOOD[1], "tool_use_id": None}, GOOD[-1]],
}


@pytest.mark.parametrize("item", sorted(NEGATIVE))
def test_each_item_fails_on_its_negative_case(tmp_path, item):
    path = tmp_path / "a.jsonl"
    head = forge(path, NEGATIVE[item])
    failures = {k for k, ok in verdicts(path, head).items() if not ok}
    assert item in failures and failures <= {item, "append-only"}


def test_unopened_taint_without_run_end_fails(tmp_path):
    path = tmp_path / "a.jsonl"
    forge(path, [GOOD[0], GOOD[2]])
    result = verdicts(path)
    assert result["taint-resolved"] is False and result["run-start-end"] is False


def test_chain_and_append_only_fail_on_tampering(tmp_path):
    path = tmp_path / "a.jsonl"
    head = forge(path, GOOD)
    rows = path.read_text().splitlines()
    record = json.loads(rows[2])
    record["payload"] = {"reason": "edited"}
    rows[2] = json.dumps(record)
    path.write_text("\n".join(rows) + "\n")
    assert verdicts(path, head)["chain-verifies"] is False
    path.write_text("\n".join(rows[:-1]) + "\n")
    assert verdicts(path, head)["append-only"] is False


def test_empty_log_fails_the_checklist(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text("")
    result = verdicts(path)
    assert not result["run-start-end"] and not result["chain-verifies"]
    assert not result["append-only"]


def test_reopening_a_cut_off_log_raises_naming_the_line(tmp_path):
    path = tmp_path / "a.jsonl"
    forge(path, GOOD)
    path.write_text(path.read_text()[:-15])
    with pytest.raises(audit.AuditError, match=f"line {len(GOOD)}"):
        audit.AuditLog(path)


def test_reopening_without_a_trailing_newline_raises(tmp_path):
    path = tmp_path / "a.jsonl"
    forge(path, GOOD)
    path.write_text(path.read_text().rstrip("\n"))
    with pytest.raises(audit.AuditError, match="cut off"):
        audit.AuditLog(path)


def test_reopening_a_non_json_last_line_raises(tmp_path):
    path = tmp_path / "a.jsonl"
    forge(path, GOOD)
    path.write_text(path.read_text() + "garbage\n")
    with pytest.raises(audit.AuditError, match=f"line {len(GOOD) + 1}"):
        audit.AuditLog(path)


def test_append_refuses_when_the_chain_does_not_verify(tmp_path):
    path = tmp_path / "a.jsonl"
    forge(path, GOOD)
    rows = path.read_text().splitlines()
    record = json.loads(rows[2])
    record["payload"] = {"reason": "edited"}
    rows[2] = json.dumps(record)
    path.write_text("\n".join(rows) + "\n")
    log = audit.AuditLog(path)
    before = path.read_text()
    with pytest.raises(audit.AuditError, match="line 3"):
        log.append(event("run.start"))
    assert path.read_text() == before


def test_append_refuses_after_the_tail_was_dropped(tmp_path):
    path = tmp_path / "a.jsonl"
    log = audit.AuditLog(path)
    log.append(event("run.start"))
    log.append(event("run.end"))
    path.write_text(path.read_text().splitlines(keepends=True)[0])
    with pytest.raises(audit.AuditError, match="truncated"):
        log.append(event("run.start"))


def test_timestamps_compare_as_instants_across_formats(tmp_path):
    log = audit.AuditLog(tmp_path / "a.jsonl")
    log.append(event("run.start", ts="2026-10-17T10:00:05Z"))
    log.append(event("tool.call", ts="2026-10-17T10:00:01.000000+00:00", tool_use_id="t"))
    log.append(event("run.end", ts="2026-10-17T12:00:06+02:00"))
    stamps = [r["ts"] for r in lines(tmp_path / "a.jsonl")]
    assert stamps == [
        "2026-10-17T10:00:05.000000+00:00",
        "2026-10-17T10:00:05.000000+00:00",
        "2026-10-17T10:00:06.000000+00:00",
    ]
    assert audit.verify(tmp_path / "a.jsonl").ok
