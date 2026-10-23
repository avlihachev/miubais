"""Vendor the JSON schemas kubeconform needs to validate stage 03 offline.

Run once with network access; the output is committed and tests never fetch anything:

    uv run --frozen python course/m6-serving-lab/fixtures/k8s-schemas/generate.py

Layout, matching the two kubeconform -schema-location patterns serving_lab.k8s passes:

    v1.31.0-standalone{,-strict}/<kind>-<group>-<version>.json
        {{ .NormalizedKubernetesVersion }}-standalone{{ .StrictSuffix }}/
        {{ .ResourceKind }}{{ .KindSuffix }}.json
        core resources, copied byte for byte from yannh/kubernetes-json-schema (the source
        kubeconform's `default` location reads over the network)
    <group>/<kind>_<version>.json
        {{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json
        CRDs, converted from each CRD's openAPIV3Schema the way datreeio/CRDs-catalog does:
        every object with properties and no additionalProperties gets
        additionalProperties: false, so -strict rejects unknown fields

Sources:
    core     https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/v1.31.0-standalone{,-strict}/
    KEDA     https://github.com/kedacore/keda/releases/download/v2.21.0/keda-2.21.0-crds.yaml
             (ScaledObject keda.sh/v1alpha1)
    GIE      https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.6.2/v1-manifests.yaml
             (InferencePool inference.networking.k8s.io/v1)
    Gateway  https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml
             (Gateway, HTTPRoute gateway.networking.k8s.io/v1)
"""

import json
import urllib.request
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent
KUBERNETES_VERSION = "v1.31.0"
CORE_BASE = "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master"
CORE_KINDS = (
    "configmap-v1",
    "deployment-apps-v1",
    "horizontalpodautoscaler-autoscaling-v2",
    "ingress-networking-v1",
    "persistentvolumeclaim-v1",
    "poddisruptionbudget-policy-v1",
    "role-rbac-v1",
    "rolebinding-rbac-v1",
    "secret-v1",
    "service-v1",
    "serviceaccount-v1",
)
CRDS = (
    (
        "https://github.com/kedacore/keda/releases/download/v2.21.0/keda-2.21.0-crds.yaml",
        "ScaledObject",
        "v1alpha1",
    ),
    (
        "https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/v1.6.2/v1-manifests.yaml",
        "InferencePool",
        "v1",
    ),
    (
        "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml",
        "Gateway",
        "v1",
    ),
    (
        "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml",
        "HTTPRoute",
        "v1",
    ),
)


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def to_json_schema(node: dict) -> dict:
    schema = dict(node)
    if "properties" in schema:
        schema["properties"] = {k: to_json_schema(v) for k, v in schema["properties"].items()}
    for key in ("items", "additionalProperties", "not"):
        if isinstance(schema.get(key), dict):
            schema[key] = to_json_schema(schema[key])
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            schema[key] = [to_json_schema(s) for s in schema[key]]
    if schema.pop("x-kubernetes-int-or-string", False):
        schema.pop("type", None)
        schema.setdefault("anyOf", [{"type": "integer"}, {"type": "string"}])
    if schema.pop("nullable", False) and isinstance(schema.get("type"), str):
        schema["type"] = [schema["type"], "null"]
    if (
        "properties" in schema
        and "additionalProperties" not in schema
        and not schema.get("x-kubernetes-preserve-unknown-fields")
    ):
        schema["additionalProperties"] = False
    return schema


def crd_schema(manifests: str, kind: str, version: str) -> tuple[str, dict]:
    for doc in yaml.safe_load_all(manifests):
        if not doc or doc.get("kind") != "CustomResourceDefinition":
            continue
        spec = doc["spec"]
        if spec["names"]["kind"] != kind:
            continue
        for v in spec["versions"]:
            if v["name"] == version:
                return spec["group"], to_json_schema(v["schema"]["openAPIV3Schema"])
    raise SystemExit(f"{kind} {version} not found")


def main() -> None:
    for variant in ("standalone", "standalone-strict"):
        target = OUT / f"{KUBERNETES_VERSION}-{variant}"
        target.mkdir(exist_ok=True)
        for name in CORE_KINDS:
            url = f"{CORE_BASE}/{KUBERNETES_VERSION}-{variant}/{name}.json"
            (target / f"{name}.json").write_bytes(fetch(url))
    downloads: dict[str, str] = {}
    for url, kind, version in CRDS:
        text = downloads.setdefault(url, fetch(url).decode())
        group, schema = crd_schema(text, kind, version)
        target = OUT / group / f"{kind.lower()}_{version}.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(schema, indent=2) + "\n")
        print(f"{target.relative_to(OUT)} <- {url}")


if __name__ == "__main__":
    main()
