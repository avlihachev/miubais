from serving_lab.types import Sample, ScaleDecision, ScalePolicy

METRIC = "vllm:num_requests_waiting"


def desired_replicas(policy: ScalePolicy, waiting: float) -> int:
    raise NotImplementedError


def simulate(policy: ScalePolicy, series: list[Sample], *, replicas0: int) -> list[ScaleDecision]:
    raise NotImplementedError


def to_scaledobject(
    policy: ScalePolicy, *, deployment: str, prometheus_url: str, model: str | None = None
) -> dict:
    raise NotImplementedError
