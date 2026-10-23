import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol, get_args

Requirement = Literal[
    "claude-auth", "api-key", "docker", "go", "node", "helm", "kubeconform", "ollama", "embed-model"
]
REQUIREMENTS: tuple[str, ...] = get_args(Requirement)


EMBED_MODEL_DIRS: tuple[tuple[str, ...], ...] = (
    (
        "models--Qdrant--bge-small-en-v1.5-onnx-Q",
        "models--BAAI--bge-small-en-v1.5",
        "fast-bge-small-en-v1.5",
    ),
    ("models--Xenova--ms-marco-MiniLM-L-6-v2", "fast-ms-marco-MiniLM-L-6-v2"),
)


def fastembed_cache_dirs() -> list[Path]:
    override = os.environ.get("FASTEMBED_CACHE_PATH")
    if override:
        return [Path(override)]
    return [Path(tempfile.gettempdir()) / "fastembed_cache", Path.home() / ".cache" / "fastembed"]


def embed_models_cached() -> bool:
    return any(
        all(any((cache / name).is_dir() for name in names) for names in EMBED_MODEL_DIRS)
        for cache in fastembed_cache_dirs()
    )


class Probe(Protocol):
    def has(self, req: Requirement) -> bool: ...


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001 - any probe failure means missing
        return None
    return result if result.returncode == 0 else None


class SystemProbe:
    def has(self, req: Requirement) -> bool:
        match req:
            case "claude-auth":
                return self._claude_logged_in()
            case "api-key":
                return bool(os.environ.get("ANTHROPIC_API_KEY"))
            case "docker":
                return _run(["docker", "info"]) is not None
            case "ollama":
                return _run(["ollama", "list"]) is not None
            case "embed-model":
                return embed_models_cached()
            case "go" | "node" | "helm" | "kubeconform":
                return shutil.which(req) is not None
        return False

    def _claude_logged_in(self) -> bool:
        result = _run(["claude", "auth", "status"])
        if result is None:
            return False
        try:
            return json.loads(result.stdout).get("loggedIn") is True
        except (ValueError, AttributeError):
            return False


def missing(reqs: list[Requirement], probe: Probe | None = None) -> list[Requirement]:
    probe = probe or SystemProbe()
    return [r for r in reqs if not probe.has(r)]
