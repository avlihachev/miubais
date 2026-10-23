import shutil
from pathlib import Path

import pytest
import yaml
from harnesskit.testing import scripted_query

LAB = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB.parent.parent
CORPUS = REPO_ROOT / "fixtures" / "injection-corpus" / "corpus.jsonl"
TINYSHOP = REPO_ROOT / "fixtures" / "tinyshop"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")
    config.addinivalue_line("markers", "slow: spawns subprocesses or a server")


@pytest.fixture
def corpus() -> Path:
    return CORPUS


@pytest.fixture
def tokens() -> dict:
    return yaml.safe_load((LAB / "tests" / "TOKENS.yaml").read_text())


@pytest.fixture
def key() -> dict:
    return yaml.safe_load((LAB / "tests" / "KEY.yaml").read_text())


@pytest.fixture
def scripted():
    return scripted_query


@pytest.fixture
def tinyshop(tmp_path):
    def copy() -> Path:
        dest = tmp_path / "tinyshop"
        shutil.copytree(
            TINYSHOP, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache")
        )
        return dest

    return copy
