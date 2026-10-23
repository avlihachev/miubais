import json
from dataclasses import replace

import pytest
from conftest import FIXTURE_EPOCH_NS
from harnesskit.testing import load_run
from trace_lab import cost, spans
from trace_lab.cost import Prices
from trace_lab.types import RunTrace


def raw(runs_dir, rid):
    return [json.loads(line) for line in (runs_dir / f"{rid}.jsonl").read_text().splitlines()]


def record(runs_dir, rid):
    provider, _ = spans.provider_for_tests()
    rows = raw(runs_dir, rid)
    trace = spans.record_run(
        load_run(runs_dir / f"{rid}.jsonl"),
        ticket_id=rows[0]["ticket_id"],
        tracer_provider=provider,
        epoch_ns=FIXTURE_EPOCH_NS,
    )
    return trace, rows


def all_runs(runs_dir):
    return {path.stem: record(runs_dir, path.stem) for path in sorted(runs_dir.glob("*.jsonl"))}


def hand_cost(usage, price):
    return (
        usage["input_tokens"] * price["input"]
        + usage["output_tokens"] * price["output"]
        + usage["cache_read_input_tokens"] * price["cache_read"]
        + usage["cache_creation_input_tokens"] * price["cache_write_5m"]
    ) / 1e6


def chat_spans(trace):
    return [s for s in trace.spans if s.attributes.get("gen_ai.operation.name") == "chat"]


def test_prices_load_reads_the_table(prices_path):
    prices = Prices.load(prices_path)
    table = json.loads(prices_path.read_text())
    assert prices.table == table
    assert Prices.load().table == table


def test_span_cost_equals_the_hand_formula(runs_dir, prices_path):
    prices = Prices.load(prices_path)
    trace, rows = record(runs_dir, "r001")
    by_id = {s.attributes["gen_ai.response.id"]: s for s in chat_spans(trace)}
    cached = [
        r
        for r in rows
        if r["type"] == "assistant"
        and r["usage"]["cache_read_input_tokens"]
        and r["usage"]["cache_creation_input_tokens"]
    ]
    assert cached
    row = cached[0]
    expected = hand_cost(row["usage"], prices.table[row["model"]])
    assert cost.span_cost(by_id[row["message_id"]], prices) == pytest.approx(expected, abs=1e-12)


def test_only_chat_spans_cost_money(runs_dir, prices_path):
    prices = Prices.load(prices_path)
    trace, _ = record(runs_dir, "r001")
    others = [s for s in trace.spans if s not in chat_spans(trace)]
    assert others
    assert all(cost.span_cost(s, prices) == 0.0 for s in others)


def test_per_task_matches_the_key(runs_dir, prices_path, key):
    prices = Prices.load(prices_path)
    runs = all_runs(runs_dir)
    tasks = cost.per_task((trace for trace, _ in runs.values()), prices)
    assert set(tasks) == set(key["cache_hit_ratio"])
    for ticket, ratio in key["cache_hit_ratio"].items():
        assert tasks[ticket].ticket_id == ticket
        assert tasks[ticket].cache_hit_ratio == pytest.approx(ratio, abs=1e-6)


def test_per_task_counts_calls_tokens_and_cost(runs_dir, prices_path):
    prices = Prices.load(prices_path)
    runs = all_runs(runs_dir)
    ticket = runs["r001"][1][0]["ticket_id"]
    mine = [(trace, rows) for trace, rows in runs.values() if rows[0]["ticket_id"] == ticket]
    assert len(mine) == 4
    task = cost.per_task([trace for trace, _ in mine], prices)[ticket]
    turns, tools, totals, usd = 0, 0, dict.fromkeys(("i", "o", "r", "w"), 0), 0.0
    for _, rows in mine:
        seen = set()
        for row in rows:
            if row["type"] != "assistant":
                continue
            tools += sum(b["type"] == "tool_use" for b in row["content"])
            if row["message_id"] in seen:
                continue
            seen.add(row["message_id"])
            turns += 1
            usage = row["usage"]
            totals["i"] += usage["input_tokens"]
            totals["o"] += usage["output_tokens"]
            totals["r"] += usage["cache_read_input_tokens"]
            totals["w"] += usage["cache_creation_input_tokens"]
            usd += hand_cost(usage, prices.table[row["model"]])
    assert task.calls == turns
    assert task.tool_calls == tools
    assert (task.input_tokens, task.output_tokens) == (totals["i"], totals["o"])
    assert (task.cache_read_tokens, task.cache_write_tokens) == (totals["r"], totals["w"])
    assert task.usd == pytest.approx(usd, abs=1e-9)


def test_reconcile_matches_the_sdk_cost_for_every_run(runs_dir, prices_path):
    prices = Prices.load(prices_path)
    checked = 0
    for rid, (trace, rows) in all_runs(runs_dir).items():
        rec = cost.reconcile(trace, prices)
        if rows[-1]["type"] != "result":
            assert rec.reported is None and rec.delta is None, rid
            assert rec.from_spans > 0, rid
            continue
        assert rec.reported == rows[-1]["total_cost_usd"], rid
        assert abs(rec.delta) < 1e-9, rid
        assert rec.delta == rec.from_spans - rec.reported, rid
        checked += 1
    assert checked == 38


def test_no_tokens_means_a_zero_ratio(prices_path):
    empty = RunTrace(trace_id="0" * 32, ticket_id="t", spans=[])
    tasks = cost.per_task([empty], Prices.load(prices_path))
    assert tasks["t"].cache_hit_ratio == 0.0
    assert tasks["t"].usd == 0.0


@pytest.mark.parametrize("price_key", ["cache_read", "cache_write_5m"])
def test_cache_tokens_priced_as_plain_input_are_caught(runs_dir, prices_path, price_key):
    prices = Prices.load(prices_path)
    wrong = replace(
        prices,
        table={
            model: {**price, price_key: price["input"]} if isinstance(price, dict) else price
            for model, price in prices.table.items()
        },
    )
    runs = {rid: run for rid, run in all_runs(runs_dir).items() if run[1][-1]["type"] == "result"}
    shift = {}
    for rid, (trace, rows) in runs.items():
        shift[rid] = abs(cost.reconcile(trace, wrong).delta) / rows[-1]["total_cost_usd"]
    no_cache = min(shift, key=lambda rid: (shift[rid], rid))
    cached = max(shift, key=lambda rid: (shift[rid], rid))
    assert shift[no_cache] < 1e-9, f"{no_cache} uses no cache, so the mistake cannot move it"
    assert shift[cached] > 0.01, f"pricing {price_key} as input moves {cached} by over 1 %"
