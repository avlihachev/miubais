import pytest
from miubais.paths import repo_root

OVERLAY = repo_root() / "publish"
START_BLOCK = "git clone https://github.com/avlihachev/miubais"

pytestmark = pytest.mark.skipif(not OVERLAY.exists(), reason="publish/ overlay is private")


def test_overlay_files_present():
    for name in ["README.md", "LICENSE", "LICENSE-CONTENT", ".github/workflows/ci.yml"]:
        assert (OVERLAY / name).is_file(), name
    assert START_BLOCK in (OVERLAY / "README.md").read_text()
    assert "MIT License" in (OVERLAY / "LICENSE").read_text()
    assert "CC BY-NC-SA 4.0" in (OVERLAY / "LICENSE-CONTENT").read_text()
