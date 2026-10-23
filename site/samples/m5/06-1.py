import json

from injection_lab_lessons import chain, verify_chain

events = [
    {"ts": "2026-10-17T09:00:00.000000+00:00", "event": "run.start", "actor": "host"},
    {"ts": "2026-10-17T09:00:04.120000+00:00", "event": "tool.call", "actor": "model"},
    {
        "ts": "2026-10-17T09:00:04.130000+00:00",
        "event": "tool.denied",
        "actor": "host",
        "reason": "untrusted content in context: approval required",
    },
    {"ts": "2026-10-17T09:00:09.500000+00:00", "event": "run.end", "actor": "host"},
]
lines = chain(events)
print(json.loads(lines[1])["prev_sha256"][:16], json.loads(lines[1])["sha256"][:16])
print("intact:", verify_chain(lines))

edited = json.loads(lines[2])
edited["reason"] = "allowed by policy"
print("edited line 3:", verify_chain([*lines[:2], json.dumps(edited), *lines[3:]]))
print("deleted line 3:", verify_chain([*lines[:2], *lines[3:]]))
print("cut after line 2:", verify_chain(lines[:2]), "<- needs the recorded head to catch")
