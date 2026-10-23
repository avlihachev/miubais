import pytest
from serving_lab.fake_server import FakeOpenAIServer


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")


@pytest.fixture
def fake_server():
    servers: list[FakeOpenAIServer] = []

    def start(**knobs) -> FakeOpenAIServer:
        server = FakeOpenAIServer(**knobs).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.stop()
