import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
import serving_lab
import yaml
from serving_lab import k8s
from serving_lab.types import CheckItem

LAB = Path(__file__).resolve().parent.parent
CHART = LAB / "fixtures" / "k8s" / "vllm-stack-0.1.13"
SCHEMAS = LAB / "fixtures" / "k8s-schemas"
WORKSPACE_K8S = Path(serving_lab.__file__).resolve().parents[2] / "k8s"
DEAD_PROXY = "http://127.0.0.1:9"
PLAIN = ("inferencepool.yaml", "httproute.yaml", "gateway.yaml", "scaledobject.yaml")
CHECK_NAMES = (
    "gpu_request",
    "runtime_class",
    "readiness_probe",
    "pdb",
    "resource_limits",
    "model_pvc",
    "hf_token_secret",
    "max_model_len",
)
LOCAL_FAILS = {
    "runtime_class",
    "pdb",
    "resource_limits",
    "model_pvc",
    "hf_token_secret",
    "max_model_len",
}

pytestmark = pytest.mark.skipif(
    not (shutil.which("helm") and shutil.which("kubeconform")), reason="needs helm and kubeconform"
)

SPY = """import json, os, sys
log = os.path.join(os.environ["MIUBAIS_SPY_DIR"], "{name}.jsonl")
env = {{k: v for k, v in os.environ.items() if k.startswith("HELM_") or "PROXY" in k.upper()}}
with open(log, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "env": env}}) + "\\n")
os.execv({real!r}, [{real!r}, *sys.argv[1:]])
"""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.setenv(var, DEAD_PROXY)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)


@pytest.fixture
def spy(tmp_path, monkeypatch):
    bin_dir, log_dir = tmp_path / "bin", tmp_path / "log"
    bin_dir.mkdir()
    log_dir.mkdir()
    for name in ("helm", "kubeconform"):
        script = bin_dir / f"{name}.py"
        script.write_text(SPY.format(name=name, real=shutil.which(name)))
        wrapper = bin_dir / name
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MIUBAIS_SPY_DIR", str(log_dir))

    def calls(name: str) -> list[dict]:
        log = log_dir / f"{name}.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return calls


def learner_file(name: str) -> Path:
    path = WORKSPACE_K8S / name
    if not path.is_file():
        pytest.fail(f"write k8s/{name} in your workspace (README, stage 03)")
    return path


def docs(manifests: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(manifests) if isinstance(d, dict)]


def dump(items: list[dict]) -> str:
    return yaml.safe_dump_all(items, sort_keys=False)


def vllm_deployments(items: list[dict]) -> list[dict]:
    return [
        d
        for d in items
        if d.get("kind") == "Deployment"
        and any(
            "vllm-openai" in c.get("image", "") for c in d["spec"]["template"]["spec"]["containers"]
        )
    ]


def vllm_container(deploy: dict) -> dict:
    return next(
        c for c in deploy["spec"]["template"]["spec"]["containers"] if "vllm-openai" in c["image"]
    )


@pytest.fixture(scope="module")
def prod() -> str:
    return k8s.render(CHART, learner_file("values-prod.yaml"))


@pytest.fixture(scope="module")
def local() -> str:
    return k8s.render(CHART, learner_file("values-local.yaml"))


def flag_value(argv: list[str], env: dict, flag: str, var: str) -> str | None:
    for i, arg in enumerate(argv):
        if arg == flag and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1]
    return env.get(var)


def is_throwaway(path: str | None) -> bool:
    if path is None:
        return False
    if path == "/dev/null":
        return True
    resolved = Path(path).resolve()
    return resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def test_render_runs_helm_template_isolated_from_repositories(spy, tmp_path, monkeypatch):
    user_repos = tmp_path / "user-repositories.yaml"
    user_repos.write_text(
        "apiVersion: ''\nrepositories:\n- name: vllm\n  url: http://127.0.0.1:9/charts\n"
    )
    monkeypatch.setenv("HELM_REPOSITORY_CONFIG", str(user_repos))
    monkeypatch.setenv("HELM_REPOSITORY_CACHE", str(tmp_path / "user-cache"))
    values = learner_file("values-prod.yaml")
    manifests = k8s.render(CHART, values)
    assert vllm_deployments(docs(manifests)), "rendered output has no vLLM Deployment"
    calls = spy("helm")
    assert calls, "render must call `helm` from PATH"
    for call in calls:
        argv, env = call["argv"], call["env"]
        assert argv[0] == "template", f"only `helm template` may run, got {argv[:2]}"
        assert str(CHART) in argv and str(values) in argv
        assert "--values" in argv or "-f" in argv or any(a.startswith("--values=") for a in argv)
        assert "--skip-tests" in argv
        assert not {"--dependency-update", "--repo"} & set(argv), "render must not fetch charts"
        repos = flag_value(argv, env, "--repository-config", "HELM_REPOSITORY_CONFIG")
        cache = flag_value(argv, env, "--repository-cache", "HELM_REPOSITORY_CACHE")
        assert repos != str(user_repos) and is_throwaway(repos), f"repository config {repos}"
        assert is_throwaway(cache), f"repository cache {cache}"
        assert env.get("HTTPS_PROXY") == DEAD_PROXY, "the test runs helm with network disabled"


def test_render_failure_raises_with_helm_message(tmp_path):
    values = tmp_path / "broken.yaml"
    values.write_text("servingEngineSpec:\n  modelSpec:\n    - name: m\n      tag: v1\n")
    with pytest.raises(RuntimeError, match="repository"):
        k8s.render(CHART, values)


def test_values_prod_renders_a_gpu_deployment(prod):
    deployments = vllm_deployments(docs(prod))
    assert deployments, "values-prod.yaml renders no vLLM Deployment"
    for deploy in deployments:
        requests = vllm_container(deploy)["resources"]["requests"]
        assert str(requests.get("nvidia.com/gpu")) == "1", deploy["metadata"]["name"]
    spec = yaml.safe_load(learner_file("values-prod.yaml").read_text())
    for model in spec["servingEngineSpec"]["modelSpec"]:
        assert model["repository"] == "vllm/vllm-openai"
        assert model["requestGPU"] == 1


@pytest.mark.parametrize("which", ["local", "prod"])
def test_rendered_values_validate_offline(which, request, spy):
    result = k8s.validate(request.getfixturevalue(which), schemas_dir=SCHEMAS)
    assert result.ok, result.errors
    assert result.errors == []
    calls = spy("kubeconform")
    assert calls, "validate must call `kubeconform` from PATH"
    for call in calls:
        argv = call["argv"]
        assert "-strict" in argv
        assert "-ignore-missing-schemas" not in argv
        locations = [argv[i + 1] for i, a in enumerate(argv) if a == "-schema-location"]
        assert locations, "pass the vendored schemas with -schema-location"
        for location in locations:
            assert location.startswith(str(SCHEMAS)), f"{location} is not a vendored schema"


def test_strict_rejects_an_unknown_field(prod):
    items = docs(prod)
    deploy = vllm_deployments(items)[0]
    deploy["spec"]["replicaz"] = 2
    strict = k8s.validate(dump(items), schemas_dir=SCHEMAS)
    assert not strict.ok
    assert any("replicaz" in e for e in strict.errors), strict.errors
    assert k8s.validate(dump(items), schemas_dir=SCHEMAS, strict=False).ok


def test_strict_rejects_an_unknown_field_in_a_course_crd():
    pool = yaml.safe_load(learner_file("inferencepool.yaml").read_text())
    pool["spec"]["weights"] = {"a": 1}
    result = k8s.validate(dump([pool]), schemas_dir=SCHEMAS)
    assert not result.ok
    assert any("weights" in e for e in result.errors), result.errors


def test_scaledobject_without_scale_target_ref_fails():
    scaled = yaml.safe_load(learner_file("scaledobject.yaml").read_text())
    del scaled["spec"]["scaleTargetRef"]
    result = k8s.validate(dump([scaled]), schemas_dir=SCHEMAS)
    assert not result.ok
    assert any("scaleTargetRef" in e for e in result.errors), result.errors


def test_a_kind_without_a_schema_is_an_error_not_a_skip():
    widget = {"apiVersion": "example.com/v1", "kind": "Widget", "metadata": {"name": "w"}}
    result = k8s.validate(dump([widget]), schemas_dir=SCHEMAS)
    assert not result.ok
    assert any("Widget" in e for e in result.errors), result.errors


def test_empty_input_is_not_valid():
    assert not k8s.validate("", schemas_dir=SCHEMAS).ok


@pytest.mark.parametrize("name", PLAIN)
def test_plain_manifests_validate(name):
    result = k8s.validate(learner_file(name).read_text(), schemas_dir=SCHEMAS)
    assert result.ok, result.errors


def test_plain_manifests_point_at_the_prod_release(prod):
    deploy = vllm_deployments(docs(prod))[0]
    pod_labels = deploy["spec"]["template"]["metadata"]["labels"]
    ports = {p["containerPort"] for p in vllm_container(deploy).get("ports", [])}
    pool = yaml.safe_load(learner_file("inferencepool.yaml").read_text())
    route = yaml.safe_load(learner_file("httproute.yaml").read_text())
    gateway = yaml.safe_load(learner_file("gateway.yaml").read_text())
    scaled = yaml.safe_load(learner_file("scaledobject.yaml").read_text())

    assert pool["apiVersion"] == "inference.networking.k8s.io/v1"
    assert pool["spec"]["selector"]["matchLabels"].items() <= pod_labels.items()
    assert {p["number"] for p in pool["spec"]["targetPorts"]} <= ports

    assert {p["name"] for p in route["spec"]["parentRefs"]} == {gateway["metadata"]["name"]}
    backends = [b for rule in route["spec"]["rules"] for b in rule.get("backendRefs", [])]
    assert any(
        b.get("kind") == "InferencePool"
        and b.get("group") == "inference.networking.k8s.io"
        and b["name"] == pool["metadata"]["name"]
        for b in backends
    ), backends

    target = scaled["spec"]["scaleTargetRef"]
    assert target["name"] == deploy["metadata"]["name"]
    assert target.get("kind", "Deployment") == "Deployment"
    trigger = scaled["spec"]["triggers"][0]
    assert trigger["type"] == "prometheus"
    assert {"serverAddress", "query", "threshold", "activationThreshold"} <= trigger[
        "metadata"
    ].keys()
    assert "vllm:num_requests_waiting" in trigger["metadata"]["query"]


def test_checklist_passes_on_values_prod(prod):
    items = k8s.checklist(prod)
    assert all(isinstance(i, CheckItem) for i in items)
    assert [i.name for i in items] == list(CHECK_NAMES)
    assert all(i.ok for i in items), [i for i in items if not i.ok]


def test_checklist_fails_values_local_for_named_reasons(local):
    items = k8s.checklist(local)
    assert [i.name for i in items] == list(CHECK_NAMES)
    assert {i.name for i in items if not i.ok} == LOCAL_FAILS
    assert all(i.detail for i in items if not i.ok)


def drop_gpu(c, pod, items):
    for section in ("requests", "limits"):
        c["resources"].get(section, {}).pop("nvidia.com/gpu", None)


def drop_runtime_class(c, pod, items):
    pod.pop("runtimeClassName", None)


def wrong_probe(c, pod, items):
    c["readinessProbe"]["httpGet"]["path"] = "/v1/models"


def drop_pdb(c, pod, items):
    items[:] = [d for d in items if d.get("kind") != "PodDisruptionBudget"]


def drop_memory_limit(c, pod, items):
    c["resources"]["limits"].pop("memory")


def empty_dir_cache(c, pod, items):
    for volume in pod["volumes"]:
        if "persistentVolumeClaim" in volume:
            del volume["persistentVolumeClaim"]
            volume["emptyDir"] = {}


def inline_token(c, pod, items):
    for env in c["env"]:
        if env["name"] == "HF_TOKEN":
            env.pop("valueFrom")
            env["value"] = "hf_example"


def drop_max_model_len(c, pod, items):
    for key in ("command", "args"):
        argv = c.get(key) or []
        if "--max-model-len" in argv:
            i = argv.index("--max-model-len")
            del argv[i : i + 2]
        c[key] = [a for a in argv if not str(a).startswith("--max-model-len=")]


@pytest.mark.parametrize(
    ("rule", "break_it"),
    [
        ("gpu_request", drop_gpu),
        ("runtime_class", drop_runtime_class),
        ("readiness_probe", wrong_probe),
        ("pdb", drop_pdb),
        ("resource_limits", drop_memory_limit),
        ("model_pvc", empty_dir_cache),
        ("hf_token_secret", inline_token),
        ("max_model_len", drop_max_model_len),
    ],
)
def test_each_rule_catches_its_own_regression(prod, rule, break_it):
    items = copy.deepcopy(docs(prod))
    deploy = vllm_deployments(items)[0]
    break_it(vllm_container(deploy), deploy["spec"]["template"]["spec"], items)
    failed = {i.name: i.detail for i in k8s.checklist(dump(items)) if not i.ok}
    assert set(failed) == {rule}, failed
    assert failed[rule]


def test_checklist_without_a_vllm_deployment_fails_every_rule():
    items = k8s.checklist(learner_file("gateway.yaml").read_text())
    assert [i.name for i in items] == list(CHECK_NAMES)
    assert not any(i.ok for i in items)
