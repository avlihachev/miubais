from pathlib import Path

import pytest
import yaml
from harnesskit.testing import scripted_query

LAB = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB.parent.parent
FIXTURE_EPOCH_NS = 1_700_000_000 * 10**9


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")


@pytest.fixture
def runs_dir():
    return REPO_ROOT / "fixtures" / "harness-runs" / "runs"


@pytest.fixture
def prices_path():
    return REPO_ROOT / "fixtures" / "harness-runs" / "prices.json"


@pytest.fixture
def key():
    return yaml.safe_load((LAB / "tests" / "KEY.yaml").read_text())


@pytest.fixture
def scripted():
    return scripted_query
