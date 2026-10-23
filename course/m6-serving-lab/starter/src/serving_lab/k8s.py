from pathlib import Path

from serving_lab.types import CheckItem, Validation

CORE_SCHEMAS = (
    "{{ .NormalizedKubernetesVersion }}-standalone{{ .StrictSuffix }}/"
    "{{ .ResourceKind }}{{ .KindSuffix }}.json"
)
CRD_SCHEMAS = "{{ .Group }}/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json"
CHECKS = (
    "gpu_request",
    "runtime_class",
    "readiness_probe",
    "pdb",
    "resource_limits",
    "model_pvc",
    "hf_token_secret",
    "max_model_len",
)


def render(chart_dir: Path, values_path: Path, *, release: str = "miubais") -> str:
    raise NotImplementedError


def validate(
    manifests: str, *, schemas_dir: Path, kubernetes_version: str = "1.31.0", strict: bool = True
) -> Validation:
    raise NotImplementedError


def checklist(manifests: str) -> list[CheckItem]:
    raise NotImplementedError
