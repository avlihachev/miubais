import shutil
import subprocess
import sys

from miubais.requirements import REQUIREMENTS, Probe, SystemProbe

Row = tuple[str, bool, str]


def _tool_version(name: str) -> Row:
    if shutil.which(name) is None:
        return (name, False, "not found")
    try:
        result = subprocess.run(
            [name, "--version"], check=False, capture_output=True, text=True, timeout=5
        )
    except Exception:  # noqa: BLE001 - any probe failure means missing
        return (name, False, "not found")
    if result.returncode != 0:
        return (name, False, "not found")
    return (name, True, result.stdout.strip())


def report(probe: Probe | None = None) -> list[Row]:
    probe = probe or SystemProbe()
    py = sys.version_info
    rows: list[Row] = [("python", py >= (3, 12), f"{py.major}.{py.minor}.{py.micro}")]
    tools = ("uv", "node", "pnpm")
    rows += [_tool_version(name) for name in tools]
    for req in REQUIREMENTS:
        if req in tools:
            continue
        ok = probe.has(req)  # type: ignore[arg-type]
        rows.append((req, ok, "available" if ok else "missing"))
    return rows
