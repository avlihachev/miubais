import pytest
from miubais.paths import course_dir

LAB = course_dir() / "m6-serving-lab"


@pytest.fixture
def support(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB / "starter" / "src"))
    monkeypatch.syspath_prepend(str(LAB / "lesson_support" / "src"))
    from serving_lab_lessons import scaling

    return scaling


def test_wanted_rounds_up_and_clamps(support):
    assert support.wanted(5, target=4, low=1, high=4) == 2
    assert support.wanted(0, target=4, low=1, high=4) == 1
    assert support.wanted(99, target=4, low=1, high=4) == 4


def test_zero_windows_repeat_each_sample(support):
    series = [(0, 1), (60, 14), (120, 1)]
    rows = support.windowed_recommendations(
        series, target=4, low=1, high=4, up_window_s=0, down_window_s=0
    )
    assert rows == [(0, 1, 1, 1), (60, 4, 4, 4), (120, 1, 1, 1)]


def test_windows_take_min_going_up_and_max_going_down(support):
    waiting = [1, 14, 1, 1, 10, 10, 10, 1, 1, 1, 1, 1, 1]
    series = [(i * 60, w) for i, w in enumerate(waiting)]
    rows = support.windowed_recommendations(
        series, target=4, low=1, high=4, up_window_s=120, down_window_s=300
    )
    assert [r[1] for r in rows] == [1, 4, 1, 1, 3, 3, 3, 1, 1, 1, 1, 1, 1]
    assert [r[2] for r in rows] == [1, 1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1]
    assert [r[3] for r in rows] == [1, 4, 4, 4, 4, 4, 4, 3, 3, 3, 3, 3, 1]
    assert [r[0] for r in rows] == [i * 60 for i in range(13)]


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB / "starter" / "src"))
    monkeypatch.syspath_prepend(str(LAB / "lesson_support" / "src"))
    from serving_lab_lessons import capacity

    return capacity


def test_nearest_rank_returns_a_member(capacity):
    values = [5, 1, 4, 2, 3]
    assert capacity.nearest_rank(values, 50) == 3
    assert capacity.nearest_rank(values, 99) == 5
    assert capacity.nearest_rank(values, 0) == 1
    assert capacity.nearest_rank([], 50) == 0.0


def test_stream_metrics_follow_the_stage_01_definitions(capacity):
    m = capacity.stream_metrics([0.5, 0.6, 0.7], 0.75)
    assert m["tokens"] == 3 and m["ttft_ms"] == pytest.approx(500)
    assert m["tps"] == pytest.approx(3 / 0.2) and m["latency_ms"] == pytest.approx(750)
    assert capacity.stream_metrics([0.4], 0.5)["tps"] is None
    assert capacity.stream_metrics([], 1.0)["ttft_ms"] is None


def test_cost_formula(capacity):
    assert capacity.throughput([10, 20], 3.0) == 10
    assert capacity.usd_per_mtok_out(3.6, 1000, 1_000_000) == pytest.approx(1.0)
    assert capacity.usd_per_mtok_out(3.6, 2000, 1_000_000) == pytest.approx(2.0)


@pytest.fixture
def finetune(monkeypatch):
    monkeypatch.syspath_prepend(str(LAB / "lesson_support" / "src"))
    from serving_lab_lessons import finetune

    return finetune


def test_lora_arithmetic(finetune):
    assert finetune.lora_params(100, 50, 4) == 600
    share = finetune.adapter_share([(100, 50), (50, 100)], 4)
    assert share == {"full": 10_000, "lora": 1_200, "share": 0.12}
    assert finetune.effective_batch(2, 4) == 8 and finetune.effective_batch(2, 4, devices=2) == 16
    assert finetune.optimizer_steps(1000, 8, 3) == 375 and finetune.optimizer_steps(9, 8, 1) == 2
