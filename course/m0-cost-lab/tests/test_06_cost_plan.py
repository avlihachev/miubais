import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from cost_lab.ledger import cost_usd, load_prices

LIVE = ["no-cache", "cache-5m", "cache-1h", "cache-by-gap"]
SUMMARY = {"batch": "summary-batch", "live": "summary-live"}
STRATEGIES = [*LIVE, *SUMMARY.values()]
BUCKETS = ["under_5m", "5m_to_60m", "over_60m"]
TTL_BY_GAP = {"under_5m": "5m", "5m_to_60m": "1h", "over_60m": None}
BATCH_MAX_HOURS = 24
TOLERANCE = 0.05
CAUSE_WORDS = ("changes", "differs", "varies", "different", "new each")


@pytest.fixture
def scenario(fixture_dir):
    return yaml.safe_load((fixture_dir / "scenario.yaml").read_text())


@pytest.fixture
def usage_log(fixture_dir, scenario):
    lines = (fixture_dir / scenario["usage_log"]).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def plan_text():
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    path = Path(root) / "COST_PLAN.md"
    if not path.is_file():
        pytest.fail(f"write {path.name} in your workspace root")
    return path.read_text()


def usage(*, uncached=0, written=0, read=0, output=0):
    return SimpleNamespace(
        input_tokens=uncached,
        output_tokens=output,
        cache_creation_input_tokens=written,
        cache_read_input_tokens=read,
    )


def prefix(s):
    return s["system_prompt_tokens"] + s["tools_tokens"]


def conversation_usd(s, prices, ttl, bucket):
    hit = (ttl == "5m" and bucket == "under_5m") or (ttl == "1h" and bucket != "over_60m")
    exchange = s["avg_user_turn_tokens"] + s["avg_assistant_turn_tokens"]
    output = s["avg_assistant_turn_tokens"]
    total = 0.0
    for k in range(1, s["turns_per_conversation"] + 1):
        rest = (k - 1) * exchange + s["avg_user_turn_tokens"]
        if ttl is None:
            u = usage(uncached=prefix(s) + rest, output=output)
        elif k == 1 or not hit:
            u = usage(uncached=rest, written=prefix(s), output=output)
        else:
            u = usage(uncached=rest, read=prefix(s), output=output)
        total += cost_usd(u, s["model"], prices, ttl=ttl or "5m", batch=False)
    return total


def summary_usd(s, prices, *, batch):
    exchange = s["avg_user_turn_tokens"] + s["avg_assistant_turn_tokens"]
    transcript = s["turns_per_conversation"] * exchange
    u = usage(uncached=prefix(s) + transcript, output=s["summary_job"]["output_tokens"])
    return cost_usd(u, s["model"], prices, ttl="5m", batch=batch)


def expected_plan(s):
    prices = load_prices()
    gaps = s["gap_distribution"]

    def live(ttl_for):
        return sum(gaps[b] * conversation_usd(s, prices, ttl_for(b), b) for b in BUCKETS)

    per_conversation = {
        "no-cache": live(lambda b: None),
        "cache-5m": live(lambda b: "5m"),
        "cache-1h": live(lambda b: "1h"),
        "cache-by-gap": live(TTL_BY_GAP.get),
        "summary-batch": summary_usd(s, prices, batch=True),
        "summary-live": summary_usd(s, prices, batch=False),
    }
    conversations = s["conversations_per_day"] * s["days"]
    return {name: usd * conversations for name, usd in per_conversation.items()}


def expected_summary(s, plan):
    if s["summary_job"]["deadline_hours"] < BATCH_MAX_HOURS:
        return "live"
    return "batch" if plan["summary-batch"] < plan["summary-live"] else "live"


def invalidated(log):
    shas: dict[str, list[str]] = {}
    for record in sorted(log, key=lambda r: r["ts"]):
        shas.setdefault(record["conversation_id"], []).append(record["system_sha"])
    return {cid for cid, seen in shas.items() if len(set(seen)) > 1}


def parse_rows(text):
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        name = cells[0].strip("`")
        if len(cells) >= 3 and name in STRATEGIES:
            try:
                rows[name] = float(cells[1].replace(",", "").lstrip("$"))
            except ValueError:
                pytest.fail(f"monthly_usd must be a plain number, got: {line}")
    return rows


def section(text, title):
    pattern = rf"^## {title}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    assert match, f"add a `## {title}` section"
    return match.group(1)


def line_value(text, key):
    match = re.search(rf"^{key}:\s*`?([^`\s]+)`?\s*$", text, re.MULTILINE)
    assert match, f"add a line `{key}: ...`"
    return match.group(1)


def test_scenario_fractions_sum_to_one(scenario):
    assert set(scenario["gap_distribution"]) == set(BUCKETS)
    assert sum(scenario["gap_distribution"].values()) == pytest.approx(1.0)


def test_plan_has_the_header_and_every_row(plan_text):
    assert "| strategy | monthly_usd | assumptions |" in plan_text
    assert set(parse_rows(plan_text)) == set(STRATEGIES)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_row_is_within_five_percent_of_the_recomputation(strategy, scenario, plan_text):
    expected = expected_plan(scenario)[strategy]
    assert parse_rows(plan_text)[strategy] == pytest.approx(expected, rel=TOLERANCE)


def test_chosen_is_the_cheapest_live_strategy(scenario, plan_text):
    plan = expected_plan(scenario)
    assert line_value(plan_text, "chosen") == min(LIVE, key=plan.get)


def test_summary_line_names_the_cheaper_allowed_option(scenario, plan_text):
    assert line_value(plan_text, "summary") == expected_summary(scenario, expected_plan(scenario))


def test_invalidator_lists_exactly_the_affected_conversations(usage_log, plan_text):
    listed = set(re.findall(r"conv-[0-9a-z]+", section(plan_text, "Invalidator")))
    assert listed == invalidated(usage_log)


def test_invalidator_names_the_cause(plan_text):
    text = section(plan_text, "Invalidator").lower()
    assert "system" in text and any(word in text for word in CAUSE_WORDS)


def test_why_section_has_at_least_eighty_words(plan_text):
    assert len(section(plan_text, "Why").split()) >= 80
