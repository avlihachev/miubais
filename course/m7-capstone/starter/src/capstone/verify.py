from pathlib import Path

from capstone.types import PR, Applied, VerifyResult


def apply_patch(repo: Path, patch: Path, dest: Path) -> Applied:
    raise NotImplementedError


def run(tree: Path, *, timeout: int = 300) -> VerifyResult:
    raise NotImplementedError


def gate(
    repo: Path, pr: PR, dest: Path | None = None, *, timeout: int = 300
) -> tuple[Applied, VerifyResult | None]:
    raise NotImplementedError
