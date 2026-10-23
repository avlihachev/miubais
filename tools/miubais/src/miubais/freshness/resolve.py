import json
import re
import subprocess
from collections.abc import Callable
from importlib import resources
from typing import Literal

import httpx
import yaml

Level = Literal["none", "patch", "minor", "major", "unknown"]
TIMEOUT = 15


def gh_api(path: str) -> dict:
    try:
        proc = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, timeout=TIMEOUT, check=True
        )
        data = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _model_latest(alias: str) -> str | None:
    text = resources.files("miubais.freshness").joinpath("models.yaml").read_text()
    entry = yaml.safe_load(text)["models"].get(alias)
    return entry["latest"] if entry else None


def _get_json(http: httpx.Client, url: str) -> dict:
    try:
        response = http.get(url, timeout=TIMEOUT)
        data = response.json() if response.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def latest(
    kind: str, name: str, *, http: httpx.Client, gh: Callable[[str], dict] | None
) -> str | None:
    match kind:
        case "pypi":
            version = _get_json(http, f"https://pypi.org/pypi/{name}/json").get("info", {})
            return version.get("version")
        case "npm":
            return _get_json(http, f"https://registry.npmjs.org/{name}/latest").get("version")
        case "github":
            if gh is None:
                return None
            tag = gh(f"repos/{name}/releases/latest").get("tag_name")
            return tag.removeprefix("v") if tag else None
        case "model":
            return _model_latest(name)
    return None


def _parts(version: str) -> tuple[int, int, int] | None:
    match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", version.strip())
    if match is None:
        return None
    major, minor, patch = (int(g or 0) for g in match.groups())
    return major, minor, patch


def drift(pinned: str, latest: str | None, *, kind: str | None = None) -> Level:
    if latest is None:
        return "unknown"
    if kind == "model":
        return "none" if pinned == latest else "major"
    a, b = _parts(pinned), _parts(latest)
    if a is None or b is None:
        return "unknown"
    if a == b:
        return "none"
    if a[0] != b[0]:
        return "major"
    return "minor" if a[1] != b[1] else "patch"
