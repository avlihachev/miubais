import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from serving_lab import benchmark
from serving_lab.types import BenchmarkInput, Summary

LAB = Path(__file__).resolve().parent.parent
SAMPLE = LAB / "fixtures" / "benchmarks" / "sample-run.json"
SECTIONS = ("## Setup", "## Load", "## Results", "## Cost model", "## Caveats")
FORMULA = (
    "cost per million output tokens = (GPU USD/h ÷ 3600 × run seconds) ÷ (output tokens / 1e6)"
)


def summary(**kw) -> Summary:
    values = {
        "n": 100,
        "failed": 0,
        "p50_ttft_ms": 210.0,
        "p90_ttft_ms": 480.0,
        "p99_ttft_ms": 900.0,
        "p50_tps": 41.0,
        "throughput_tps": 500.0,
        "wall_s": 300.0,
    }
    return Summary(**(values | kw))


def inputs(**kw) -> BenchmarkInput:
    values = {
        "gpu": "H100",
        "gpu_usd_per_hour": 2.5,
        "model": "Qwen/Qwen3.5-27B",
        "quantisation": "fp8",
        "tp_size": 1,
        "max_model_len": 16384,
        "summary": summary(),
        "run_s": 360.0,
        "api_usd_per_mtok_out": None,
    }
    return BenchmarkInput(**(values | kw))


def nearest_rank(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def test_formula_on_hand_computed_inputs():
    report = benchmark.from_inputs(inputs())
    assert report.output_tokens == 150_000
    assert report.output_tokens_per_hour == pytest.approx(1_500_000)
    assert report.usd_per_mtok_out == pytest.approx(0.25 / 0.15)
    assert report.usd_per_request == pytest.approx(0.0025)
    assert report.api_usd_per_mtok_out is None
    assert report.input == inputs()


def test_cost_per_request_divides_by_successful_requests():
    report = benchmark.from_inputs(inputs(summary=summary(failed=20)))
    assert report.usd_per_request == pytest.approx(0.25 / 80)


def test_idle_billed_seconds_raise_the_cost():
    busy = benchmark.from_inputs(inputs(run_s=300.0))
    idle = benchmark.from_inputs(inputs(run_s=600.0))
    assert busy.usd_per_mtok_out == pytest.approx(2.5 / 3600 * 300 / 0.15)
    assert idle.usd_per_mtok_out == pytest.approx(2 * busy.usd_per_mtok_out)
    assert idle.output_tokens_per_hour == pytest.approx(busy.output_tokens_per_hour / 2)


@pytest.mark.parametrize("price", [0.98, 2.46, 2.95, 7.0])
def test_gpu_price_is_an_input_not_a_constant(price):
    report = benchmark.from_inputs(inputs(gpu_usd_per_hour=price))
    assert report.usd_per_mtok_out == pytest.approx(price / 3600 * 360 / 0.15)
    assert report.usd_per_request == pytest.approx(price / 3600 * 360 / 100)
    assert f"{price:.2f} USD/h" in benchmark.render(report)


@pytest.mark.parametrize(
    "bad",
    [
        {"gpu_usd_per_hour": 0.0},
        {"run_s": 0.0},
        {"run_s": 299.0},
        {"summary": summary(throughput_tps=0.0)},
        {"summary": summary(failed=100)},
    ],
)
def test_impossible_inputs_are_rejected(bad):
    with pytest.raises(ValueError):
        benchmark.from_inputs(inputs(**bad))


def test_render_fills_every_section_of_the_template():
    report = benchmark.from_inputs(inputs(api_usd_per_mtok_out=20.0))
    text = benchmark.render(report)
    positions = [text.index(section) for section in SECTIONS]
    assert positions == sorted(positions)
    assert text.startswith("# Benchmark: Qwen/Qwen3.5-27B on H100\n")
    assert "{" not in text and "}" not in text
    for row in (
        "| GPU | H100 at 2.50 USD/h |",
        "| quantisation | fp8 |",
        "| tensor parallel size | 1 |",
        "| max model length | 16384 |",
        "| TTFT p50 (ms) | 210.0 |",
        "| TTFT p90 (ms) | 480.0 |",
        "| TTFT p99 (ms) | 900.0 |",
        "| TPS p50 (tokens/s per request) | 41.0 |",
        "| throughput (output tokens/s) | 500.0 |",
        "| output tokens | 150000 |",
        "| this run | 1.67 |",
        "| API list price | 20.00 |",
    ):
        assert row in text
    assert "100 requests, 0 failed, over 300.0 s of load; 360.0 s of GPU time billed." in text
    assert FORMULA in text
    assert "= (2.50 ÷ 3600 × 360.0) ÷ (150000 / 1e6) = 1.67 USD" in text
    assert "1,500,000 output tokens per hour" in text
    assert "costs 0.0025 USD" in text
    caveats = text[text.index("## Caveats") :].lower()
    for caveat in ("single run", "cold cache", "no sla"):
        assert caveat in caveats


def test_render_without_an_api_price_says_so():
    text = benchmark.render(benchmark.from_inputs(inputs()))
    assert "| API list price | not given |" in text


def test_render_uses_the_template_file():
    assert benchmark.TEMPLATE.name == "BENCHMARK_TEMPLATE.md" and benchmark.TEMPLATE.is_file()
    template = benchmark.TEMPLATE.read_text()
    for section in SECTIONS:
        assert section in template
    report = benchmark.from_inputs(inputs())
    assert benchmark.render(report).splitlines()[-1] == template.rstrip("\n").splitlines()[-1]


def test_sample_run_is_synthetic_and_internally_consistent():
    data = json.loads(SAMPLE.read_text())
    assert data["synthetic"] is True and "not measured" in data["note"].lower()
    s, setup, requests = data["summary"], data["setup"], data["requests"]
    assert len(requests) == s["n"] == 64 and s["failed"] == 0
    tokens = sum(r["output_tokens"] for r in requests)
    assert tokens == setup["max_tokens"] * s["n"]
    assert round(s["throughput_tps"] * s["wall_s"]) == tokens
    for key, p in (("p50_ttft_ms", 50), ("p90_ttft_ms", 90), ("p99_ttft_ms", 99)):
        assert s[key] == nearest_rank([r["ttft_ms"] for r in requests], p)
    assert s["p50_tps"] == nearest_rank([r["tps"] for r in requests], 50)
    for r in requests:
        decode_ms = r["output_tokens"] / r["tps"] * 1000
        assert r["ttft_ms"] + decode_ms <= r["latency_ms"] <= r["ttft_ms"] + decode_ms + 10
    latencies = [r["latency_ms"] / 1000 for r in requests]
    assert max(latencies) <= s["wall_s"]
    assert sum(latencies) / setup["concurrency"] <= s["wall_s"]


def test_cli_renders_the_sample_run(tmp_path, capsys):
    out = tmp_path / "BENCHMARK.md"
    argv = ["--input", str(SAMPLE), "--gpu", "H100", "--usd-per-hour", "2.5", "--out", str(out)]
    assert benchmark.main(argv) == 0
    printed = capsys.readouterr().out
    assert printed == out.read_text()
    data = json.loads(SAMPLE.read_text())
    s = data["summary"]
    tokens = round(s["throughput_tps"] * s["wall_s"])
    expected = 2.5 / 3600 * s["wall_s"] / (tokens / 1e6)
    assert f"| this run | {expected:.2f} |" in printed
    assert f"{s['wall_s']:.1f} s of GPU time billed" in printed
    assert "# Benchmark: Qwen/Qwen3.5-27B on H100" in printed


def test_cli_price_and_overrides_flow_through(capsys):
    argv = ["--input", str(SAMPLE), "--gpu", "L40S", "--usd-per-hour", "1.0", "--run-s", "60"]
    argv += ["--api-usd-per-mtok-out", "20", "--quantisation", "awq"]
    assert benchmark.main(argv) == 0
    printed = capsys.readouterr().out
    assert "| GPU | L40S at 1.00 USD/h |" in printed
    assert "| quantisation | awq |" in printed
    assert "| API list price | 20.00 |" in printed
    assert "60.0 s of GPU time billed" in printed


def test_cli_requires_the_gpu_price():
    with pytest.raises(SystemExit) as exc:
        benchmark.main(["--input", str(SAMPLE), "--gpu", "H100"])
    assert exc.value.code == 2


def test_cli_runs_as_a_module():
    env = {**os.environ, "PYTHONPATH": str(Path(benchmark.__file__).resolve().parents[1])}
    argv = ["--input", str(SAMPLE), "--gpu", "H100", "--usd-per-hour", "2.5"]
    run = subprocess.run(
        [sys.executable, "-m", "serving_lab.benchmark", *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "## Cost model" in run.stdout
