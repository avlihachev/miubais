from pathlib import Path

import pytest
import yaml
from harnesskit.testing import scripted_query

LAB = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB.parent.parent


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")


@pytest.fixture
def traces_dir():
    return REPO_ROOT / "fixtures" / "evals-traces" / "traces"


@pytest.fixture
def gold():
    return yaml.safe_load((LAB / "tests" / "GOLD.yaml").read_text())


@pytest.fixture
def fake_answers_path():
    return LAB / "tests" / "FAKEJUDGE.yaml"


@pytest.fixture
def stage_lists():
    return yaml.safe_load((LAB / "tests" / "STAGE_LISTS.yaml").read_text())


@pytest.fixture
def scripted():
    return scripted_query
