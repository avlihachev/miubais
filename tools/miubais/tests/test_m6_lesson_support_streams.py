import pytest
from miubais.paths import course_dir

LAB = course_dir() / "m6-serving-lab"


@pytest.fixture
def lessons(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB / "starter" / "src"))
    monkeypatch.syspath_prepend(str(LAB / "lesson_support" / "src"))
    from serving_lab_lessons import engine_budget, local_runs, streams

    return {"budget": engine_budget, "runs": local_runs, "streams": streams}


def test_tally_skips_role_finish_usage_and_done(lessons):
    s = lessons["streams"]
    arrivals = [
        (10.0, s.chunk({"role": "assistant"})),
        (11.0, ": keep-alive"),
        (12.0, ""),
        (30.0, s.chunk({"content": "a"})),
        (80.0, s.chunk({"content": "b"})),
        (81.0, s.chunk({}, finish_reason="stop")),
        (82.0, s.usage_chunk(3, 2)),
        (83.0, s.DONE),
        (99.0, s.chunk({"content": "after done"})),
    ]
    t = s.tally(arrivals, sent_ms=5.0)
    assert (t.content_tokens, t.text, t.ttft_ms) == (2, "ab", 25.0)
    assert t.tps == pytest.approx(2 / 0.05)
    assert (t.finish_reason, t.usage_completion_tokens, t.done) == ("stop", 2, True)


def test_tally_reasoning_only_and_cut_stream(lessons):
    s = lessons["streams"]
    thinking = [(5.0 * i, s.chunk({"reasoning": "x"})) for i in range(1, 4)]
    t = s.tally([*thinking, (20.0, s.chunk({"reasoning_content": "y"})), (21.0, s.DONE)])
    assert (t.content_tokens, t.reasoning_chunks, t.ttft_ms, t.tps) == (0, 4, None, None)
    assert t.first_reasoning_ms == 5.0 and t.done
    cut = s.tally([(1.0, s.chunk({"content": "only"}))])
    assert cut.content_tokens == 1 and cut.tps is None and not cut.done


def test_budget_arithmetic(lessons):
    b = lessons["budget"]
    assert b.weight_bytes(27e9, 8) == 27e9
    assert b.kv_bytes_per_token(16, 4, 256, 2) == 65_536
    got = b.budget(
        gpu_gb=80,
        utilization=0.92,
        params=27e9,
        bits_per_weight=8,
        overhead_gb=5,
        attention_layers=16,
        kv_heads=4,
        head_dim=256,
        kv_bytes_per_value=1,
    )
    assert got.weights_gb == pytest.approx(27.0) and got.kv_gb == pytest.approx(41.6)
    assert got.kv_tokens == int(41.6e9 // 32_768) and got.sequences(32_768) == 38
    starved = b.budget(
        gpu_gb=10,
        utilization=0.9,
        params=27e9,
        bits_per_weight=16,
        overhead_gb=1,
        attention_layers=16,
        kv_heads=4,
        head_dim=256,
        kv_bytes_per_value=2,
    )
    assert starved.kv_gb == 0.0 and starved.kv_tokens == 0


def test_local_run_summary_reads_only_aggregates(lessons):
    r = lessons["runs"]
    s = r.local_run_summary(LAB / "fixtures" / "live_local_model_run.json")
    assert s["requests"] == 8 and s["output_tokens"] == 330 and s["rounds"] == 4
    assert s["at_or_above_p50"] == 5
    assert s["ttft_plus_decode_s"] == pytest.approx(2.2815 + 330 / 8 / 24.8)
    local = r.local_route_latencies(LAB / "fixtures" / "live_gateway_run.json")
    assert local == [(548.1, 31), (644.6, 31), (748.3, 44)]
