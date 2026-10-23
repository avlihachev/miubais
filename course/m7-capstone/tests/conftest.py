from pathlib import Path

import pytest
import yaml
from harnesskit.testing import scripted_query

LAB = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB.parent.parent
FIXTURE = REPO_ROOT / "fixtures" / "go-ts-mini"
PR_IDS = [f"pr-{n:02d}" for n in range(1, 13)]


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")
    config.addinivalue_line("markers", "slow: spawns subprocesses over the fixture")


@pytest.fixture
def repo():
    return FIXTURE


@pytest.fixture
def prs():
    from capstone.types import PR

    return [PR.load(FIXTURE / "prs" / pr_id) for pr_id in PR_IDS]


@pytest.fixture
def labels():
    return yaml.safe_load((LAB / "tests" / "LABELS.yaml").read_text())


@pytest.fixture
def key():
    return yaml.safe_load((LAB / "tests" / "KEY.yaml").read_text())


@pytest.fixture
def fake_review():
    return LAB / "tests" / "FAKEREVIEW.yaml"


@pytest.fixture
def scripted():
    return scripted_query
