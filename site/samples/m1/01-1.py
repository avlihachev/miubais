from pathlib import Path

from harness_lab_lessons import decide

REPO = Path("/work/tinyshop")
ROOTS = [REPO / "src"]

calls = [
    ("Write", {"file_path": "src/tinyshop/pricing.py"}),
    ("Write", {"file_path": "src/../tests/test_pricing.py"}),
    ("Bash", {"command": "rm -rf build"}),
    ("Bash", {"command": "pytest -q > /tmp/report.txt"}),
    ("Read", {"file_path": "/etc/hosts"}),
    ("WebFetch", {"url": "https://example.com"}),
]

for tool, args in calls:
    ruling = decide(tool, args, ROOTS, cwd=REPO)
    shown = next(iter(args.values()))
    verdict = "allow" if ruling.allowed else "DENY"
    print(f"{verdict:<5} {tool:<8} {shown:<30} {ruling.reason}")
