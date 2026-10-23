from types import SimpleNamespace

import pytest
from anthropic.types import CacheCreation, Usage
from cost_lab.ledger import Ledger, cost_usd, load_prices


@pytest.fixture
def P():
    return load_prices()


def usage(input=0, cache_read=0, cache_creation=0, output=0):
    return SimpleNamespace(
        input_tokens=input,
        output_tokens=output,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_creation,
    )


def test_opus_cost_with_cache_read(P):
    u = usage(input=500, cache_read=10000, output=200)
    expected = (500 * 4 + 10000 * 0.20 + 200 * 20) / 1e6
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx(expected)


def test_five_minute_write_uses_write_price(P):
    u = usage(cache_creation=1000)
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx(1000 * 5.0 / 1e6)


def test_one_hour_write_uses_higher_price(P):
    u = usage(cache_creation=1000)
    assert cost_usd(u, "claude-opus-5-5", P, ttl="1h") == pytest.approx(1000 * 8.0 / 1e6)


def test_batch_halves_the_cost(P):
    u = usage(input=500, output=200)
    full = cost_usd(u, "claude-opus-5-5", P)
    assert cost_usd(u, "claude-opus-5-5", P, batch=True) == pytest.approx(full * 0.5)


def test_write_split_reported_by_the_api_is_priced_per_ttl(P):
    u = usage(cache_creation=1000)
    u.cache_creation = SimpleNamespace(ephemeral_5m_input_tokens=600, ephemeral_1h_input_tokens=400)
    expected = (600 * 5.0 + 400 * 8.0) / 1e6
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx(expected)


def test_sdk_usage_object_is_read_directly(P):
    u = Usage(
        input_tokens=100,
        output_tokens=10,
        cache_creation_input_tokens=300,
        cache_read_input_tokens=0,
        cache_creation=CacheCreation(ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=300),
    )
    expected = (100 * 4 + 300 * 8.0 + 10 * 20) / 1e6
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx(expected)


def test_explicit_ttl_overrides_the_reported_split(P):
    u = usage(cache_creation=1000)
    u.cache_creation = SimpleNamespace(ephemeral_5m_input_tokens=1000, ephemeral_1h_input_tokens=0)
    assert cost_usd(u, "claude-opus-5-5", P, ttl="1h") == pytest.approx(1000 * 8.0 / 1e6)


def test_batch_service_tier_gets_the_discount(P):
    u = usage(input=500, output=200)
    full = cost_usd(u, "claude-opus-5-5", P)
    u.service_tier = "batch"
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx(full * 0.5)
    assert cost_usd(u, "claude-opus-5-5", P, batch=False) == pytest.approx(full)


def test_fast_mode_uses_fast_prices(P):
    u = usage(input=1000, output=100)
    u.speed = "fast"
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx((1000 * 8 + 100 * 40) / 1e6)


def test_fast_mode_without_a_fast_tier_raises(P):
    u = usage(input=1000, output=100)
    u.speed = "fast"
    with pytest.raises(ValueError, match="fast"):
        cost_usd(u, "claude-sonnet-5-5", P)


def test_haiku_prompt_over_100k_uses_the_second_tier(P):
    at_limit = usage(input=80_000, cache_read=20_000, output=1000)
    over = usage(input=80_001, cache_read=20_000, output=1000)
    standard = (80_000 * 0.10 + 20_000 * 0.01 + 1000 * 0.50) / 1e6
    long = (80_001 * 0.50 + 20_000 * 0.05 + 1000 * 2.50) / 1e6
    assert cost_usd(at_limit, "claude-haiku-5-5", P) == pytest.approx(standard)
    assert cost_usd(over, "claude-haiku-5-5", P) == pytest.approx(long)


def test_iterations_are_summed_when_present(P):
    u = usage(input=23_000, output=1000)
    u.iterations = [
        SimpleNamespace(type="compaction", input_tokens=180_000, output_tokens=3500),
        SimpleNamespace(type="message", input_tokens=23_000, output_tokens=1000),
    ]
    expected = ((180_000 + 23_000) * 4 + (3500 + 1000) * 20) / 1e6
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx(expected)


def test_haiku_prices(P):
    u = usage(input=1000, cache_read=2000, cache_creation=500, output=100)
    expected = (1000 * 0.10 + 2000 * 0.01 + 500 * 0.125 + 100 * 0.50) / 1e6
    assert cost_usd(u, "claude-haiku-5-5", P) == pytest.approx(expected)


def test_unknown_model_raises_key_error(P):
    with pytest.raises(KeyError):
        cost_usd(usage(input=1), "claude-unknown", P)


def test_none_cache_fields_cost_as_zero(P):
    u = usage(input=1000, output=100)
    u.cache_read_input_tokens = None
    u.cache_creation_input_tokens = None
    assert cost_usd(u, "claude-opus-5-5", P) == pytest.approx((1000 * 4 + 100 * 20) / 1e6)


def test_ledger_totals_and_labels(P):
    ledger = Ledger(P)
    a = ledger.add("classify", usage(input=1000, output=100), "claude-haiku-5-5")
    ledger.add("classify", usage(input=1000, output=100), "claude-haiku-5-5")
    ledger.add("answer", usage(input=500, cache_read=1500, output=200), "claude-opus-5-5")
    by_label = ledger.by_label()
    assert set(by_label) == {"classify", "answer"}
    assert by_label["classify"] == pytest.approx(2 * a.usd)
    assert ledger.total() == pytest.approx(sum(by_label.values()))
    assert ledger.cache_hit_ratio() == pytest.approx(1500 / 4000)


def test_empty_ledger_has_zero_ratio_and_total(P):
    assert Ledger(P).total() == 0 and Ledger(P).cache_hit_ratio() == 0


def test_ledger_markdown_has_header_and_label_row(P):
    ledger = Ledger(P)
    ledger.add("answer", usage(input=500, cache_read=1500, output=200), "claude-opus-5-5")
    lines = ledger.to_markdown().splitlines()
    assert lines[0] == "| label | model | prompt tokens | cached % | output | usd |"
    assert set(lines[1].replace("|", "").replace(" ", "")) <= {"-", ":"}
    assert lines[2].startswith("| answer | claude-opus-5-5 | 2000 | 75.0% | 200 |")
