import os

import anthropic
import pytest
from cost_lab.prefix import build_request, cache_report

MODEL = "claude-haiku-5-5"
MIN_HIT_RATIO = 0.8
SYSTEM_STATIC = " ".join(
    ["The price list is reviewed every quarter and every SKU keeps a stable id."] * 350
)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="needs api-key")
def test_ten_requests_read_the_cached_prefix_after_the_first():
    client = anthropic.Anthropic()
    reports = []
    for i in range(1, 11):
        params = build_request(
            model=MODEL,
            max_tokens=16,
            system_static=SYSTEM_STATIC,
            tools=[],
            history=[],
            user_turn=f"question {i}",
        )
        params["thinking"] = {"type": "disabled"}
        reports.append(cache_report(client.messages.create(**params).usage))
    later = reports[1:]
    ratio = sum(r.read for r in later) / sum(r.total_prompt for r in later)
    assert ratio >= MIN_HIT_RATIO, [(r.written, r.read, r.uncached) for r in reports]
