import subprocess

from miubais import requirements
from miubais.requirements import SystemProbe, missing


def test_missing_uses_probe():
    class P:
        def has(self, r):
            return r == "docker"

    assert missing(["docker", "go"], P()) == ["go"]


def test_api_key_reads_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert SystemProbe().has("api-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert not SystemProbe().has("api-key")


def test_which_based_requirement(monkeypatch):
    monkeypatch.setattr(
        requirements.shutil, "which", lambda name: "/bin/go" if name == "go" else None
    )
    assert SystemProbe().has("go")
    assert not SystemProbe().has("helm")


def run_returning(stdout="", returncode=0):
    def fake(cmd, **kwargs):
        assert kwargs["timeout"] == 5
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return fake


def test_claude_auth_parses_logged_in(monkeypatch):
    monkeypatch.setattr(requirements.subprocess, "run", run_returning('{"loggedIn": true}'))
    assert SystemProbe().has("claude-auth")
    monkeypatch.setattr(requirements.subprocess, "run", run_returning('{"loggedIn": false}'))
    assert not SystemProbe().has("claude-auth")
    monkeypatch.setattr(requirements.subprocess, "run", run_returning("not json"))
    assert not SystemProbe().has("claude-auth")


def test_command_failure_means_missing(monkeypatch):
    monkeypatch.setattr(requirements.subprocess, "run", run_returning(returncode=1))
    assert not SystemProbe().has("docker")

    def boom(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(requirements.subprocess, "run", boom)
    assert not SystemProbe().has("ollama")


def _fake_cache(tmp_path, *names):
    for name in names:
        (tmp_path / name).mkdir()


def test_embed_model_present_when_both_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    _fake_cache(
        tmp_path,
        "models--Qdrant--bge-small-en-v1.5-onnx-Q",
        "models--Xenova--ms-marco-MiniLM-L-6-v2",
    )
    assert SystemProbe().has("embed-model")


def test_embed_model_accepts_legacy_names(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    _fake_cache(tmp_path, "fast-bge-small-en-v1.5", "fast-ms-marco-MiniLM-L-6-v2")
    assert SystemProbe().has("embed-model")


def test_embed_model_missing_when_one_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    _fake_cache(tmp_path, "models--Qdrant--bge-small-en-v1.5-onnx-Q")
    assert not SystemProbe().has("embed-model")


def test_enum_lists_embed_model():
    assert "embed-model" in requirements.REQUIREMENTS
