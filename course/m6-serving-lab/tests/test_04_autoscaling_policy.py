import json
import shutil
from pathlib import Path

import pytest
import yaml
from serving_lab import autoscale, k8s
from serving_lab.types import Sample, ScaleDecision, ScalePolicy

LAB = Path(__file__).resolve().parent.parent
SERIES = LAB / "fixtures" / "k8s" / "metrics-series.json"
SCHEMAS = LAB / "fixtures" / "k8s-schemas"
PROMETHEUS = "http://prometheus-operated.monitoring.svc:9090"
DEPLOYMENT = "miubais-qwen35-27b-deployment-vllm"
POLICY = ScalePolicy(
    min_replicas=1,
    max_replicas=4,
    target_waiting=4,
    activation=1,
    stabilisation_s=120,
    cooldown_s=300,
)
NOON = 12 * 3600
BLIP = 10 * 3600 + 30 * 60

needs_kubeconform = pytest.mark.skipif(not shutil.which("kubeconform"), reason="needs kubeconform")


def day() -> list[Sample]:
    data = json.loads(SERIES.read_text())
    return [Sample(s["t_s"], s["waiting"], s["running"]) for s in data["samples"]]


def series(*waiting: float, step: int = 60) -> list[Sample]:
    return [Sample(i * step, w, 0) for i, w in enumerate(waiting)]


def replicas_over_time(decisions: list[ScaleDecision], start: int) -> list[int]:
    return [start, *(d.replicas for d in decisions)]


def test_fixture_is_a_synthetic_day_with_a_blip_and_a_lunch_spike():
    data = json.loads(SERIES.read_text())
    samples = day()
    assert data["synthetic"] is True and data["metric"] == "vllm:num_requests_waiting"
    assert len(samples) == 1440 and samples[-1].t_s == 86340
    high = [s.t_s for s in samples if s.waiting > POLICY.target_waiting]
    assert BLIP in high and BLIP - 60 not in high and BLIP + 60 not in high
    assert {t for t in high if t != BLIP} == set(range(NOON, NOON + 3600, 60))
    assert all(s.running == 8 for s in samples if s.waiting > 0)


def test_desired_replicas_is_ceil_of_waiting_over_target_clamped():
    assert autoscale.desired_replicas(POLICY, 0) == 1
    assert autoscale.desired_replicas(POLICY, 1) == 1
    assert autoscale.desired_replicas(POLICY, 4) == 1
    assert autoscale.desired_replicas(POLICY, 4.5) == 2
    assert autoscale.desired_replicas(POLICY, 9) == 3
    assert autoscale.desired_replicas(POLICY, 12) == 3
    assert autoscale.desired_replicas(POLICY, 400) == 4


def test_activation_threshold_keeps_a_scale_to_zero_policy_at_zero():
    policy = ScalePolicy(0, 4, target_waiting=4, activation=2, stabilisation_s=0, cooldown_s=60)
    assert autoscale.desired_replicas(policy, 2) == 0
    assert autoscale.desired_replicas(policy, 2.5) == 1
    assert autoscale.simulate(policy, series(2, 2, 2, 2), replicas0=0) == []
    decisions = autoscale.simulate(policy, series(0, 3, 3), replicas0=0)
    assert [(d.t_s, d.replicas) for d in decisions] == [(60, 1)]


def test_activation_threshold_does_not_hold_back_a_running_deployment():
    policy = ScalePolicy(1, 4, target_waiting=4, activation=10, stabilisation_s=0, cooldown_s=60)
    assert autoscale.desired_replicas(policy, 0) == 1
    assert autoscale.desired_replicas(policy, 8) == 2


def test_one_sample_blip_does_not_scale():
    blip = autoscale.simulate(POLICY, series(0, 0, 0, 40, 0, 0, 0, 0), replicas0=1)
    assert blip == []
    morning = [s for s in day() if s.t_s < NOON]
    assert autoscale.simulate(POLICY, morning, replicas0=1) == []


def test_lunch_spike_scales_to_three_then_back_after_cooldown():
    decisions = autoscale.simulate(POLICY, day(), replicas0=1)
    assert [(d.t_s, d.replicas) for d in decisions] == [(NOON + 120, 3), (NOON + 3600 + 300, 1)]
    assert decisions[0].reason.startswith("up")
    assert decisions[1].reason.startswith("down")


def test_scale_up_waits_for_the_stabilisation_window():
    decisions = autoscale.simulate(POLICY, series(0, 9, 9, 9, 9), replicas0=1)
    assert [(d.t_s, d.replicas) for d in decisions] == [(180, 3)]


def test_scale_up_takes_the_lowest_recommendation_in_the_window():
    decisions = autoscale.simulate(POLICY, series(0, 5, 16, 16, 16), replicas0=1)
    assert [(d.t_s, d.replicas) for d in decisions] == [(180, 2), (240, 4)]


def test_zero_stabilisation_scales_on_the_sample():
    policy = ScalePolicy(1, 4, target_waiting=4, activation=1, stabilisation_s=0, cooldown_s=300)
    decisions = autoscale.simulate(policy, series(0, 9), replicas0=1)
    assert [(d.t_s, d.replicas) for d in decisions] == [(60, 3)]


def test_max_replicas_is_never_exceeded():
    decisions = autoscale.simulate(POLICY, series(*[1000] * 20), replicas0=1)
    assert [d.replicas for d in decisions] == [4]


def test_min_replicas_is_never_undercut():
    decisions = autoscale.simulate(POLICY, series(*[0] * 20), replicas0=3)
    assert [(d.t_s, d.replicas) for d in decisions] == [(300, 1)]


def test_scale_down_waits_for_the_cooldown_after_the_last_change():
    waiting = [9, 9, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    decisions = autoscale.simulate(POLICY, series(*waiting), replicas0=1)
    assert [(d.t_s, d.replicas) for d in decisions] == [(120, 3), (480, 1)]


def test_scale_down_takes_the_highest_recommendation_in_the_window():
    waiting = [0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 0, 0]
    decisions = autoscale.simulate(POLICY, series(*waiting), replicas0=4)
    assert [(d.t_s, d.replicas) for d in decisions] == [(300, 2), (660, 1)]


def test_replicas0_outside_the_bounds_is_clamped_at_the_first_sample():
    decisions = autoscale.simulate(POLICY, series(0, 0), replicas0=7)
    assert [(d.t_s, d.replicas) for d in decisions] == [(0, 4)]
    assert decisions[0].reason.startswith("clamp")
    assert autoscale.simulate(POLICY, [], replicas0=1) == []


def test_replicas_stay_within_bounds_over_the_day():
    for policy in (POLICY, ScalePolicy(2, 3, 2, 0.5, 60, 120)):
        decisions = autoscale.simulate(policy, day(), replicas0=policy.min_replicas)
        replicas = replicas_over_time(decisions, policy.min_replicas)
        assert all(policy.min_replicas <= r <= policy.max_replicas for r in replicas)
        times = [d.t_s for d in decisions]
        assert times == sorted(times)


def scaledobject(**kw) -> dict:
    return autoscale.to_scaledobject(POLICY, deployment=DEPLOYMENT, prometheus_url=PROMETHEUS, **kw)


def test_scaledobject_mirrors_the_policy():
    obj = scaledobject(model="Qwen/Qwen3.5-27B")
    assert obj["apiVersion"] == "keda.sh/v1alpha1" and obj["kind"] == "ScaledObject"
    spec = obj["spec"]
    assert spec["scaleTargetRef"]["name"] == DEPLOYMENT
    assert spec["scaleTargetRef"].get("kind", "Deployment") == "Deployment"
    assert (spec["minReplicaCount"], spec["maxReplicaCount"]) == (1, 4)
    assert spec["cooldownPeriod"] == 300
    behavior = spec["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]
    assert behavior["scaleUp"]["stabilizationWindowSeconds"] == 120
    assert behavior["scaleDown"]["stabilizationWindowSeconds"] == 300
    [trigger] = spec["triggers"]
    assert trigger["type"] == "prometheus"
    assert trigger["metadata"] == {
        "serverAddress": PROMETHEUS,
        "query": 'sum(vllm:num_requests_waiting{model_name="Qwen/Qwen3.5-27B"})',
        "threshold": "4",
        "activationThreshold": "1",
    }


def test_scaledobject_without_a_model_sums_every_model():
    metadata = scaledobject()["spec"]["triggers"][0]["metadata"]
    assert metadata["query"] == "sum(vllm:num_requests_waiting)"
    half = ScalePolicy(1, 4, 2.5, 0.5, 0, 60)
    other = autoscale.to_scaledobject(half, deployment="d", prometheus_url=PROMETHEUS)
    trigger = other["spec"]["triggers"][0]["metadata"]
    assert (trigger["threshold"], trigger["activationThreshold"]) == ("2.5", "0.5")


@needs_kubeconform
def test_generated_scaledobject_validates_against_the_vendored_schema():
    result = k8s.validate(yaml.safe_dump(scaledobject(model="m")), schemas_dir=SCHEMAS)
    assert result.ok, result.errors


@needs_kubeconform
def test_numeric_trigger_metadata_fails_the_schema():
    obj = scaledobject()
    obj["spec"]["triggers"][0]["metadata"]["threshold"] = 4
    assert not k8s.validate(yaml.safe_dump(obj), schemas_dir=SCHEMAS).ok
