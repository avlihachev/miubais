from dataclasses import replace

import pytest
from conftest import FIXTURE_EPOCH_NS
from harnesskit.testing import load_run
from trace_lab import query, spans
from trace_lab.cost import Prices, per_task
from trace_lab.types import RunTrace, TaskCost


def traces(runs_dir):
    provider, _ = spans.provider_for_tests()
    out = []
    for path in sorted(runs_dir.glob("*.jsonl")):
        timed = load_run(path)
        out.append(
            spans.record_run(
                timed,
                ticket_id=timed[0].message["ticket_id"],
                tracer_provider=provider,
                epoch_ns=FIXTURE_EPOCH_NS,
            )
        )
    return out


def task(ticket_id, usd):
    return TaskCost(ticket_id, usd, 1, 0, 1, 1, 0, 0, 0.0)


def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


@pytest.fixture
def prices(prices_path):
    return Prices.load(prices_path)


def test_top_five_matches_the_key(runs_dir, prices, key):
    rows = query.top_costly(traces(runs_dir), prices)
    assert [row.ticket_id for row in rows] == key["top_five"]


def test_rows_are_the_stage_02_totals(runs_dir, prices):
    recorded = traces(runs_dir)
    totals = per_task(recorded, prices)
    rows = query.top_costly(recorded, prices, n=10)
    assert len(rows) == 10
    assert rows == sorted(totals.values(), key=lambda t: (-t.usd, t.ticket_id))
    assert [row.usd for row in rows] == sorted((row.usd for row in rows), reverse=True)


def test_n_limits_the_rows(runs_dir, prices, key):
    rows = query.top_costly(traces(runs_dir), prices, n=2)
    assert [row.ticket_id for row in rows] == key["top_five"][:2]


def test_ties_break_by_ticket_id(monkeypatch, prices):
    tied = {t.ticket_id: t for t in [task("b", 1.0), task("c", 2.0), task("a", 1.0)]}
    monkeypatch.setattr(query, "per_task", lambda traces, prices: tied)
    rows = query.top_costly([RunTrace("0", "x", [])], prices, n=3)
    assert [row.ticket_id for row in rows] == ["c", "a", "b"]


def test_markdown_has_a_header_and_five_rows(runs_dir, prices):
    rows = query.top_costly(traces(runs_dir), prices)
    lines = query.to_markdown(rows).strip().splitlines()
    assert cells(lines[0]) == ["ticket", "usd", "calls", "cache-hit %"]
    assert set(lines[1]) <= set("|-: ")
    body = [cells(line) for line in lines[2:]]
    assert len(body) == 5
    for (ticket, usd, calls, hit), row in zip(body, rows, strict=True):
        assert ticket == row.ticket_id
        assert float(usd) == pytest.approx(row.usd, abs=5e-5)
        assert int(calls) == row.calls
        assert float(hit) == pytest.approx(row.cache_hit_ratio * 100, abs=0.05)


def test_cache_hit_column_is_a_percentage(prices):
    row = replace(task("001-x", 1.0), cache_hit_ratio=0.8494)
    line = query.to_markdown([row]).strip().splitlines()[2]
    assert float(cells(line)[3]) == pytest.approx(84.9, abs=0.05)


def test_cli_prints_the_table(runs_dir, key, capsys):
    assert query.main([str(runs_dir), "--top", "5"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert cells(lines[0]) == ["ticket", "usd", "calls", "cache-hit %"]
    assert [cells(line)[0] for line in lines[2:]] == key["top_five"]
