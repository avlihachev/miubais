import json
import os
import shutil
import subprocess

import pytest
import yaml
from injection_lab import corpus as corpus_mod
from injection_lab import redteam

PURPOSE = "a coding agent that reads tinyshop tickets and fixes the code they describe"


def test_generated_config_targets_the_fake_target(tmp_path, corpus):
    cases = redteam.cases(corpus_mod.load(corpus))
    with redteam.FakeTarget() as target:
        path = tmp_path / "promptfooconfig.yaml"
        redteam.write(redteam.config(target.url, purpose=PURPOSE, tests=cases), path)
        loaded = yaml.safe_load(path.read_text())
    assert loaded["targets"][0]["config"]["url"] == target.url
    assert len(loaded["tests"]) == len(cases) > 0
    evaluated = redteam.eval_config(loaded)
    assert "redteam" not in evaluated and evaluated["tests"] == loaded["tests"]
    assert evaluated["defaultTest"]["options"]["provider"].startswith("anthropic:messages:")


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs api-key")
@pytest.mark.skipif(shutil.which("npx") is None, reason="needs node")
def test_promptfoo_eval_against_the_fake_target(tmp_path, corpus):
    cases = redteam.cases(corpus_mod.load(corpus))
    config, out = tmp_path / "promptfooconfig.yaml", tmp_path / "out.json"
    env = {**os.environ, "PROMPTFOO_DISABLE_TELEMETRY": "1", "PROMPTFOO_DISABLE_UPDATE": "1"}
    with redteam.FakeTarget() as target:
        full = redteam.config(target.url, purpose=PURPOSE, tests=cases)
        redteam.write(redteam.eval_config(full), config)
        proc = subprocess.run(
            [
                "npx",
                "-y",
                redteam.PROMPTFOO,
                "eval",
                "-c",
                str(config),
                "--no-cache",
                "-o",
                str(out),
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=1100,
        )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    report = json.loads(out.read_text())
    results = report.get("results", {}).get("results", [])
    assert len(results) >= 1
