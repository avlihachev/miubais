import asyncio

import pytest
from miubais.model import AgentSdkClient, ModelRequest

pytestmark = pytest.mark.slow


@pytest.mark.live
def test_agent_sdk_client_answers(tmp_path):
    req = ModelRequest(
        system="Answer with one word.", prompt="Say OK", cwd=tmp_path, allowed_tools=[], max_turns=1
    )
    r = asyncio.run(AgentSdkClient().complete(req))
    assert "OK" in r.text.upper()
