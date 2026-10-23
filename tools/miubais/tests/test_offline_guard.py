import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.slow


def run_pytest(tmp_path, body: str, *args: str) -> subprocess.CompletedProcess:
    (tmp_path / "test_probe.py").write_text(textwrap.dedent(body))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, "test_probe.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


QUERY = """
    import asyncio
    from claude_agent_sdk import query

    def test_calls_the_model():
        async def go():
            async for _ in query(prompt="hi"):
                pass
        asyncio.run(go())
"""


def test_query_fails_under_the_plugin(tmp_path):
    proc = run_pytest(tmp_path, QUERY, "-p", "miubais.offline_guard")
    assert proc.returncode == 1
    assert "live call under offline grading" in proc.stdout


def test_module_attribute_is_guarded_too(tmp_path):
    body = """
        import claude_agent_sdk

        def test_calls_the_model():
            claude_agent_sdk.query(prompt="hi")
    """
    proc = run_pytest(tmp_path, body, "-p", "miubais.offline_guard")
    assert "live call under offline grading" in proc.stdout


def test_client_connect_fails_under_the_plugin(tmp_path):
    body = """
        import asyncio
        from claude_agent_sdk import ClaudeSDKClient

        def test_connects():
            asyncio.run(ClaudeSDKClient().connect())
    """
    proc = run_pytest(tmp_path, body, "-p", "miubais.offline_guard")
    assert proc.returncode == 1
    assert "live call under offline grading" in proc.stdout


@pytest.mark.parametrize("client", ["Anthropic", "AsyncAnthropic"])
def test_network_anthropic_client_fails_under_the_plugin(tmp_path, client):
    body = f"""
        import anthropic

        def test_builds_a_client():
            anthropic.{client}(api_key="k")
    """
    proc = run_pytest(tmp_path, body, "-p", "miubais.offline_guard")
    assert proc.returncode == 1
    assert "live call under offline grading" in proc.stdout


def test_recorded_transport_client_is_allowed(tmp_path):
    body = """
        import anthropic
        import httpx2

        def test_builds_a_recorded_client():
            transport = httpx2.MockTransport(lambda request: httpx2.Response(200))
            anthropic.Anthropic(api_key="k", http_client=httpx2.Client(transport=transport))
    """
    proc = run_pytest(tmp_path, body, "-p", "miubais.offline_guard")
    assert proc.returncode == 0, proc.stdout


def test_without_the_plugin_nothing_is_patched(tmp_path):
    body = """
        import claude_agent_sdk

        def test_untouched():
            assert claude_agent_sdk.query.__module__ == "claude_agent_sdk.query"
    """
    proc = run_pytest(tmp_path, body)
    assert proc.returncode == 0, proc.stdout
