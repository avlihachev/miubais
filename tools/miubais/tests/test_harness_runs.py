import json
import subprocess
import sys
from collections import Counter, defaultdict

import yaml
from harnesskit.testing import load_run
from miubais.paths import course_dir, repo_root

DATASET = repo_root() / "fixtures" / "harness-runs"
RUNS = DATASET / "runs"
KEY_PATH = course_dir() / "m3-trace-lab" / "tests" / "KEY.yaml"
M0_PRICES = course_dir() / "m0-cost-lab" / "starter" / "src" / "cost_lab" / "prices.json"
CAUSES = {"no-cache", "loop", "big-context", "retries", "expensive-model"}
TRUNCATED = {"r014", "r039"}


def records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def all_runs() -> dict[str, list[dict]]:
    return {path.stem: records(path) for path in sorted(RUNS.glob("*.jsonl"))}


def unique_assistants(rows: list[dict]) -> dict[str, dict]:
    return {r["message_id"]: r for r in rows if r["type"] == "assistant"}


def run_cost(rows: list[dict], prices: dict) -> float:
    total = 0.0
    for row in unique_assistants(rows).values():
        usage, price = row["usage"], prices[row["model"]]
        total += (
            usage["input_tokens"] * price["input"]
            + usage["output_tokens"] * price["output"]
            + usage["cache_read_input_tokens"] * price["cache_read"]
            + usage["cache_creation_input_tokens"] * price["cache_write_5m"]
        ) / 1e6
    return total


def test_regenerating_is_byte_identical(tmp_path):
    out, keys = tmp_path / "out", tmp_path / "keys"
    subprocess.run(
        [sys.executable, str(DATASET / "generate.py"), "--out", str(out), "--keys", str(keys)],
        check=True,
    )
    committed = sorted(p.name for p in RUNS.glob("*.jsonl"))
    assert sorted(p.name for p in (out / "runs").glob("*.jsonl")) == committed
    for name in committed:
        assert (out / "runs" / name).read_bytes() == (RUNS / name).read_bytes(), name
    for name in ("prices.json", "MANIFEST.md"):
        assert (out / name).read_bytes() == (DATASET / name).read_bytes(), name
    assert (keys / "KEY.yaml").read_bytes() == KEY_PATH.read_bytes()


def test_prices_are_the_m0_table():
    assert (DATASET / "prices.json").read_bytes() == M0_PRICES.read_bytes()


def test_forty_runs_ten_tickets_four_each():
    runs = all_runs()
    assert list(runs) == [f"r{i:03d}" for i in range(1, 41)]
    tickets = Counter(rows[0]["ticket_id"] for rows in runs.values())
    assert len(tickets) == 10 and set(tickets.values()) == {4}
    assert all(rows[0]["type"] == "meta" and rows[0]["t_ms"] == 0 for rows in runs.values())
    assert {"001-discount-rounding", "002-negative-quantity", "003-out-of-stock-message"} <= set(
        tickets
    )


def test_every_run_loads_through_harnesskit():
    for path in sorted(RUNS.glob("*.jsonl")):
        assert len(load_run(path)) == len(path.read_text().splitlines()), path.name


def test_every_cause_is_planted_at_least_twice():
    key = yaml.safe_load(KEY_PATH.read_text())
    tickets = {rows[0]["ticket_id"] for rows in all_runs().values()}
    assert set(key["causes"]) == tickets
    counts = Counter(key["causes"].values())
    assert set(counts) == CAUSES and min(counts.values()) >= 2


def test_top_five_by_recomputed_cost_matches_the_key():
    prices = json.loads((DATASET / "prices.json").read_text())
    key = yaml.safe_load(KEY_PATH.read_text())
    by_ticket: dict[str, float] = defaultdict(float)
    for rows in all_runs().values():
        by_ticket[rows[0]["ticket_id"]] += run_cost(rows, prices)
    ranked = sorted(by_ticket, key=lambda t: (-by_ticket[t], t))
    assert ranked[:5] == key["top_five"]
    assert by_ticket[ranked[4]] - by_ticket[ranked[5]] > 0.005


def test_result_cost_follows_the_formula():
    prices = json.loads((DATASET / "prices.json").read_text())
    for rid, rows in all_runs().items():
        result = rows[-1]
        if result["type"] != "result":
            continue
        expected = run_cost(rows, prices)
        assert abs(result["total_cost_usd"] - expected) < 1e-9, rid
        [(model, usage)] = result["model_usage"].items()
        assert abs(usage["costUSD"] - expected) < 1e-9, rid
        assert result["num_turns"] == len(unique_assistants(rows)), rid
        totals = Counter()
        for row in unique_assistants(rows).values():
            totals.update(row["usage"])
            assert row["model"] == model, rid
        assert result["usage"] == dict(totals), rid


def test_cache_hit_ratio_in_the_key():
    key = yaml.safe_load(KEY_PATH.read_text())
    parts: dict[str, Counter] = defaultdict(Counter)
    for rows in all_runs().values():
        for row in unique_assistants(rows).values():
            parts[rows[0]["ticket_id"]].update(row["usage"])
    for ticket, p in parts.items():
        total = p["input_tokens"] + p["cache_read_input_tokens"] + p["cache_creation_input_tokens"]
        assert abs(key["cache_hit_ratio"][ticket] - p["cache_read_input_tokens"] / total) < 1e-12
    no_cache = [t for t, c in key["causes"].items() if c == "no-cache"]
    assert all(key["cache_hit_ratio"][t] == 0.0 for t in no_cache)


def test_assistant_messages_carry_usage_and_ids():
    for rid, rows in all_runs().items():
        for row in rows:
            if row["type"] == "assistant":
                assert row["message_id"].startswith("msg_"), rid
                assert set(row["usage"]) == {
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                }, rid
                assert row["usage"]["output_tokens"] > 0, rid


def test_shared_message_ids_have_identical_usage_in_three_runs_or_more():
    sharing = 0
    for rows in all_runs().values():
        groups = defaultdict(list)
        for row in rows:
            if row["type"] == "assistant":
                groups[row["message_id"]].append(row)
        shared = [g for g in groups.values() if len(g) > 1]
        for group in shared:
            assert all(r["usage"] == group[0]["usage"] for r in group)
        sharing += bool(shared)
    assert sharing >= 3


def test_tool_uses_get_results_except_in_truncated_runs():
    readme = (DATASET / "README.md").read_text()
    assert all(rid in readme for rid in TRUNCATED)
    endings = {}
    for rid, rows in all_runs().items():
        uses = {
            b["id"]
            for r in rows
            if r["type"] == "assistant"
            for b in r["content"]
            if b["type"] == "tool_use"
        }
        results = {b["tool_use_id"] for r in rows if r["type"] == "user" for b in r["content"]}
        assert results <= uses, rid
        if rid in TRUNCATED:
            assert uses - results, rid
        else:
            assert uses == results, rid
        endings[rid] = rows[-1].get("subtype", "truncated")
    assert {r for r, e in endings.items() if e == "truncated"} == TRUNCATED
    assert Counter(endings.values())["error_max_turns"] == 1


def test_planted_causes_show_in_the_runs():
    key = yaml.safe_load(KEY_PATH.read_text())
    for rid, rows in all_runs().items():
        cause = key["causes"][rows[0]["ticket_id"]]
        assistants = unique_assistants(rows).values()
        if cause == "no-cache":
            assert all(r["usage"]["cache_read_input_tokens"] == 0 for r in assistants), rid
        else:
            assert sum(r["usage"]["cache_read_input_tokens"] for r in assistants) > 0, rid
        uses = [
            b
            for r in rows
            if r["type"] == "assistant"
            for b in r["content"]
            if b["type"] == "tool_use"
        ]
        if cause == "loop":
            commands = Counter(b["input"]["command"] for b in uses if b["name"] == "Bash")
            assert max(commands.values()) >= 4, rid
        if cause == "big-context":
            biggest = max(
                sum(v for k, v in r["usage"].items() if k != "output_tokens") for r in assistants
            )
            assert biggest >= 60_000, rid
        if cause == "retries":
            errors = [b for r in rows if r["type"] == "user" for b in r["content"] if b["is_error"]]
            assert len(errors) == 2, rid
    models = defaultdict(set)
    for rows in all_runs().values():
        models[rows[0]["ticket_id"]] |= {r["model"] for r in unique_assistants(rows).values()}
    for ticket, cause in key["causes"].items():
        if cause == "expensive-model":
            assert models[ticket] == {"claude-opus-5-5", "claude-haiku-5-5"}, ticket


def test_tool_results_follow_their_call_within_bounds():
    for rid, rows in all_runs().items():
        called = {}
        for row in rows:
            if row["type"] == "assistant":
                for block in row["content"]:
                    if block["type"] == "tool_use":
                        called[block["id"]] = row["t_ms"]
            elif row["type"] == "user":
                for block in row["content"]:
                    delay = row["t_ms"] - called[block["tool_use_id"]]
                    assert 50 <= delay <= 900, rid
        times = [row["t_ms"] for row in rows]
        assert times == sorted(times), rid


def test_manifest_lists_every_run_as_synthetic():
    manifest = (DATASET / "MANIFEST.md").read_text()
    for path in sorted(RUNS.glob("*.jsonl")):
        assert f"| runs/{path.name} | synthetic |" in manifest
