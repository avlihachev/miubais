import httpx
import pytest
from miubais.freshness.resolve import drift, gh_api, latest


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == "https://pypi.org/pypi/langfuse/json":
        return httpx.Response(200, json={"info": {"version": "5.0.2"}})
    if url == "https://registry.npmjs.org/@astrojs/starlight/latest":
        return httpx.Response(200, json={"version": "0.43.0"})
    return httpx.Response(404)


@pytest.fixture
def mock_http():
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_pypi_latest_and_drift(mock_http):
    assert latest("pypi", "langfuse", http=mock_http, gh=None) == "5.0.2"
    assert drift("3.4.0", "5.0.2") == "major" and drift("5.0.2", "5.0.2") == "none"


def test_npm_latest(mock_http):
    assert latest("npm", "@astrojs/starlight", http=mock_http, gh=None) == "0.43.0"


def test_missing_package_is_none(mock_http):
    assert latest("pypi", "nope", http=mock_http, gh=None) is None


def test_network_error_is_none():
    def boom(request):
        raise httpx.ConnectError("down")

    http = httpx.Client(transport=httpx.MockTransport(boom))
    assert latest("npm", "x", http=http, gh=None) is None


def test_github_strips_v_prefix(mock_http):
    calls = []

    def gh(path):
        calls.append(path)
        return {"tag_name": "v1.2.3"}

    assert latest("github", "owner/repo", http=mock_http, gh=gh) == "1.2.3"
    assert calls == ["repos/owner/repo/releases/latest"]


def test_github_failure_is_none(mock_http):
    assert latest("github", "owner/repo", http=mock_http, gh=lambda p: {}) is None
    assert latest("github", "owner/repo", http=mock_http, gh=None) is None


def test_model_lookup_by_alias(mock_http):
    assert latest("model", "default", http=mock_http, gh=None) == "claude-opus-5-5"
    assert latest("model", "haiku", http=mock_http, gh=None) == "claude-haiku-5-5"
    assert latest("model", "unknown-alias", http=mock_http, gh=None) is None


def test_gh_api_returns_empty_when_gh_fails(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert gh_api("repos/a/b/releases/latest") == {}


@pytest.mark.parametrize(
    ("pinned", "new", "level"),
    [
        ("1.2.3", "1.2.3", "none"),
        ("1.2.3", "1.2.4", "patch"),
        ("1.2.3", "1.3.0", "minor"),
        ("1.2.3", "2.0.0", "major"),
        ("v1.2", "1.2.0", "none"),
        ("1.2.3rc1", "1.2.3", "none"),
        ("abc", "1.0.0", "unknown"),
        ("1.0.0", None, "unknown"),
    ],
)
def test_drift_levels(pinned, new, level):
    assert drift(pinned, new) == level


def test_model_drift_compares_ids():
    assert drift("claude-opus-5-5", "claude-opus-5-5", kind="model") == "none"
    assert drift("claude-opus-4-1", "claude-opus-5-5", kind="model") == "major"
