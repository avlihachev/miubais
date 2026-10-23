import asyncio
import base64
import dataclasses
import json
import random
import string

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from injection_lab.corpus import load
from injection_lab.detect import score
from injection_lab.provenance import Taint, post_hook
from injection_lab.secrets import guard_env, scrub, scrub_hook, subprocess_env
from injection_lab.types import SECRET_KINDS

SAMPLES = {
    "anthropic-key": "sk-ant-api03-Zx9fakeFAKEfake0123456789",
    "langfuse-key": "sk-lf-0a1b2c3d-fake-4e5f",
    "aws-access-key": "AKIAFAKEFAKEFAKE0123",
    "github-token": "ghp_FAKEfakeFAKEfake0123456789abcd",
    "private-key": "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAfake\nBBBBfake\n-----END OPENSSH PRIVATE KEY-----",
    "bearer-token": "Bearer fake0123456789.token",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.ZmFrZS1zaWduYXR1cmU",
    "env-secret": "DB_PASSWORD=fake-hunter2",
}


@pytest.mark.parametrize("kind", sorted(SAMPLES))
def test_each_pattern_is_redacted(kind):
    redaction = scrub(f"before {SAMPLES[kind]} after")
    assert f"[REDACTED:{kind}]" in redaction.text
    assert redaction.counts == {kind: 1}
    assert redaction.text.startswith("before ") and redaction.text.endswith(" after")


def test_every_secret_kind_has_a_sample():
    assert set(SAMPLES) == set(SECRET_KINDS)


def test_names_stay_and_values_go():
    text = "export API_KEY='abc def'\nGITHUB_TOKEN=xyz123\nPATH=/usr/bin\nAuthorization: Bearer abcd1234efgh5678ijkl"
    redacted = scrub(text).text
    assert redacted == (
        "export API_KEY=[REDACTED:env-secret]\nGITHUB_TOKEN=[REDACTED:env-secret]\n"
        "PATH=/usr/bin\nAuthorization: Bearer [REDACTED:bearer-token]"
    )


def test_langfuse_public_keys_count_too():
    assert scrub("pk-lf-1234abcd-ef").counts == {"langfuse-key": 1}


def test_secrets_inside_nested_json_strings():
    inner = json.dumps(
        {"ANTHROPIC_API_KEY": "plain-value-1", "note": f"use {SAMPLES['aws-access-key']}"}
    )
    text = json.dumps({"config": inner, "ok": "fine"})
    redaction = scrub(text)
    assert "plain-value-1" not in redaction.text and "AKIAFAKE" not in redaction.text
    assert redaction.counts == {"env-secret": 1, "aws-access-key": 1}
    decoded = json.loads(json.loads(redaction.text)["config"])
    assert decoded["ANTHROPIC_API_KEY"] == "[REDACTED:env-secret]"
    assert json.loads(redaction.text)["ok"] == "fine"


def test_base64_blobs_that_decode_to_a_key():
    blob = base64.b64encode(f"token: {SAMPLES['github-token']}".encode()).decode()
    redaction = scrub(f"cache entry {blob} end")
    assert redaction.text == "cache entry [REDACTED:github-token] end"
    harmless = base64.b64encode(b"just a harmless sentence about carts").decode()
    assert scrub(f"cache entry {harmless}").text == f"cache entry {harmless}"


def test_non_secret_text_is_never_altered(corpus):
    rng = random.Random(20261017)
    alphabet = string.ascii_letters + string.digits + string.punctuation + " \n\t-_=:"
    texts = [item.text for item in load(corpus)]
    texts += ["".join(rng.choices(alphabet, k=rng.randint(1, 300))) for _ in range(200)]
    for text in texts:
        redaction = scrub(text)
        assert redaction.text == text, text
        assert redaction.counts == {}


def test_subprocess_env_is_an_allowlist(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-fake")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("TERM", raising=False)
    env = subprocess_env()
    assert env["PATH"] == "/usr/bin" and env["LANG"] == "C.UTF-8"
    assert set(env) <= {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM"}
    assert "TERM" not in env
    assert subprocess_env({"SHOP_URL": "http://x"})["SHOP_URL"] == "http://x"


def test_guard_env_replaces_the_options_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake")
    options = ClaudeAgentOptions(env={"SHOP_URL": "http://x"}, max_turns=3)
    guarded = guard_env(options)
    assert guarded.env == subprocess_env({"SHOP_URL": "http://x"})
    assert "GITHUB_TOKEN" not in guarded.env
    assert dataclasses.replace(guarded, env=options.env) == options


def test_scrub_hook_rewrites_tool_output():
    seen: list[dict] = []
    hook = scrub_hook(on_redact=seen.append)
    response = {"stdout": f"key={SAMPLES['anthropic-key']}", "stderr": "", "interrupted": False}
    data = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {},
        "tool_response": response,
    }
    output = asyncio.run(hook(data, "tu-1", None))
    assert output["hookSpecificOutput"]["updatedToolOutput"] == {
        "stdout": "key=[REDACTED:anthropic-key]",
        "stderr": "",
        "interrupted": False,
    }
    assert seen == [{"anthropic-key": 1}]
    clean = dict(data, tool_response="nothing here")
    assert asyncio.run(hook(clean, "tu-2", None)) == {}


def test_scrubbing_happens_before_wrapping():
    hook = post_hook(Taint(), score, scrub=lambda text: scrub(text).text)
    data = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": ".env"},
        "tool_response": "GITHUB_TOKEN=ghp_FAKEfakeFAKEfake0123456789abcd",
    }
    text = asyncio.run(hook(data, "tu-1", None))["hookSpecificOutput"]["updatedToolOutput"]
    assert "ghp_" not in text and "GITHUB_TOKEN=[REDACTED:github-token]" in text


def test_bearer_tokens_without_digits_are_redacted():
    assert scrub("Authorization: Bearer abcdefghijklmnopqrstuv").text == (
        "Authorization: Bearer [REDACTED:bearer-token]"
    )


def test_bearer_prose_is_left_alone():
    for text in ("We use Bearer authentication.", "Bearer tokens expire after an hour."):
        redaction = scrub(text)
        assert redaction.text == text and redaction.counts == {}


def test_yaml_and_ini_secret_values_are_redacted():
    text = (
        "db:\n  Password: hunter2hunter2\n  host: localhost\n"
        "API_KEY: 'abc def'  # rotate monthly\n- secret: s3cr3t\n"
        "[auth]\ntoken = xyz123\nmax_tokens: 512\n"
    )
    redaction = scrub(text)
    assert redaction.text == (
        "db:\n  Password: [REDACTED:env-secret]\n  host: localhost\n"
        "API_KEY: [REDACTED:env-secret]  # rotate monthly\n- secret: [REDACTED:env-secret]\n"
        "[auth]\ntoken = [REDACTED:env-secret]\nmax_tokens: 512\n"
    )
    assert redaction.counts == {"env-secret": 4}


def test_hex_encoded_keys_are_redacted():
    hexed = f"ANTHROPIC_API_KEY={SAMPLES['anthropic-key']}".encode().hex()
    redaction = scrub(f"blob {hexed} end")
    assert redaction.text == "blob [REDACTED:anthropic-key] end"
    digest = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    assert scrub(f"sha256 {digest}").counts == {}


def test_lower_case_secret_names_are_redacted():
    text = 'password=hunter2\napi_key = abc\n{"access_token": "zzz", "token_type": "Bearer"}'
    assert scrub(text).text == (
        "password=[REDACTED:env-secret]\napi_key = [REDACTED:env-secret]\n"
        '{"access_token": "[REDACTED:env-secret]", "token_type": "Bearer"}'
    )


def test_scrub_hook_fails_closed(monkeypatch):
    import injection_lab.secrets as secrets_mod

    def boom(text):
        raise RuntimeError("scrubber crashed")

    monkeypatch.setattr(secrets_mod, "scrub", boom)
    errors: list[Exception] = []
    hook = scrub_hook(on_error=errors.append)
    data = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {},
        "tool_response": {"stdout": "API_KEY=sk-ant-api03-fake", "interrupted": False},
    }
    output = asyncio.run(hook(data, "tu-1", None))
    assert output["hookSpecificOutput"]["updatedToolOutput"] == {
        "stdout": "[REDACTED:error]",
        "interrupted": False,
    }
    assert len(errors) == 1
    string_data = dict(data, tool_response="API_KEY=sk-ant-api03-fake")
    assert asyncio.run(hook(string_data, "tu-2", None)) == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": "[REDACTED:error]",
        }
    }
