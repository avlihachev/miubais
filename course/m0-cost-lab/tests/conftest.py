from pathlib import Path

import pytest
from cost_lab.transport import make_client


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")


@pytest.fixture
def fixture_dir():
    return Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture
def client_for(fixture_dir):
    def build(sequence: list[str]):
        return make_client(fixture_dir, sequence)

    return build
