# Prompt caching as prefix engineering

**Prerequisites:** [lesson 02](../02-kv-cache-and-batching/), for why a reused prefix saves compute, and the `usage` counters from [lesson 01](../01-tokens-prefill-decode/).

## Why this matters for the factory

Lesson 01 showed that in an agent loop the bill is mostly input: every turn re-sends the system prompt, the tool definitions and the growing history. Prompt caching is the lever that turns that repeated prefill into a cheap read. On Opus 5.5 a cached read costs $0.20 per million tokens against $4 for uncached input, 5% of the price (Claude pricing), and it also skips the prefill time for those tokens. For a factory running thousands of agent sessions a day over the same 20K-token system prompt and tool set, whether caching works is the difference between a viable unit cost and a cost line someone asks you to explain.

Caching is easy to switch on and easy to break without noticing. Nothing errors when it misses: the request succeeds, the answer is the same, and you pay the full price or, worse, the write premium on every call. You have probably used caching through the Agent SDK or Claude Code, where the harness lays out the prompt for you. This lesson is about doing it yourself on the raw Messages API: designing the prefix, placing breakpoints, picking a TTL on the numbers, and proving from `usage` that it hits.

## Core idea

The cache is keyed on an exact prefix. The API renders a request in a fixed order, `tools`, then `system`, then `messages`, and a cache hit requires that the rendered prefix up to a breakpoint matches a recent request byte for byte (Prompt caching; Mid-conversation system messages). It is the same contract as vLLM's automatic prefix caching from lesson 02, where each KV block's hash chains through every earlier token: change one token early and everything after it is new.

```
 rendered request (hash order) ----------------------------------------->
 +-----------+------------------+------------------------+--------------+
 |  tools    |  system (static) |  history (grows)       |  new turn    |
 +-----------+------------------+------------------------+--------------+
                               ^                         ^
              breakpoint 1: tools + system      breakpoint 2 (or automatic):
              shared by every session           this session's history
 a change here ...  invalidates everything to its right
```

So prompt design becomes layout design. Put what never changes first, what changes per session next, and what changes per turn last. Mark the end of each stable region with a breakpoint. Everything to the left of a breakpoint must be deterministic down to the byte: same tool order, same JSON key order, no clocks, no ids.

The mechanics in brief, all from the Prompt caching page. You can set up to 4 explicit breakpoints with `cache_control` on content blocks, or add a single top-level `cache_control` to the request (automatic caching), which places the breakpoint on the last cacheable block and moves it forward as the conversation grows; automatic caching uses one of the 4 slots, and with 4 explicit breakpoints already present the API returns 400. The minimum cacheable prefix is 512 tokens on Opus 5.5, Sonnet 5.5 and Haiku 5.5 (1,024 on Opus 4.8 and Sonnet 5, 2,048 on Opus 4.7, 4,096 on Opus 4.6 and Haiku 4.5); below it the request is processed without caching and no error is returned. At each breakpoint the API looks back at most 20 block positions for an earlier entry, so a request that adds 20 or more positions since the last cache write can miss unless a second breakpoint sits closer. On the Claude API a run of consecutive `tool_use` blocks counts as one position, and so does a run of `tool_result` blocks, so a parallel fan-out alone does not push the previous entry out of the window.

## Mechanics

### The TTL decision, on the numbers

Cache writes cost more than plain input; reads cost much less. On Opus 5.5 (Claude pricing, checked 2026-10-17):

| | Price per MTok | Multiple of $4 input |
| --- | ---: | ---: |
| 5-minute write (default) | $5.00 | 1.25x |
| 1-hour write (`"ttl": "1h"`) | $8.00 | 2x |
| Cache read or refresh | $0.20 | 0.05x |

A 5-minute write costs 0.25x extra and each read saves 0.95x, so it pays off after one read. A 1-hour write costs 1.0x extra, so it needs two reads. Each read refreshes the TTL at no extra cost (Prompt caching), which means a busy loop keeps a 5-minute entry alive indefinitely.

The decision comes down to the gap between requests that share the prefix, not the session length. Take a 50,000-token prefix and six turns ten minutes apart, as in a review agent that waits on a human between turns. No cache: 6 x 50K x $4/MTok = $1.20. With a 5-minute TTL every turn arrives after expiry and writes again: 6 x 50K x $5/MTok = $1.50, worse than not caching. With a 1-hour TTL: one write at $8/MTok ($0.40) plus five reads at $0.20/MTok ($0.05), $0.45 in total. If the same six turns come 30 seconds apart, the 5-minute TTL costs $0.25 + $0.05 = $0.30 and is the right choice. Measure the inter-request gap distribution of your workload before you pick; tool calls that run CI or wait for approval routinely exceed five minutes.

### Building the request and reading `usage`

`usage` splits the prompt into three counters: `cache_creation_input_tokens` (written this request), `cache_read_input_tokens` (served from cache) and `input_tokens` (the uncached remainder after the last breakpoint). The total prompt is the sum of the three (Prompt caching, "Tracking cache performance"). If you only log `input_tokens`, a perfectly cached 100K-token request looks like a 40-token one and a broken cache looks normal.

The principle is that everything which never changes goes first and is serialised the same way every time, the breakpoint sits at the end of that static part, and everything that changes goes after it. For a chat assistant with tools, a request built that way has this shape:

```
{
  "model": "claude-opus-5-5",
  "tools": [ ...the same tools on every turn, in a fixed order, schema keys in a fixed order... ],
  "system": [{"type": "text", "text": "<static rules>", "cache_control": {"type": "ephemeral"}}],
  "messages": [ ...history..., {"role": "user", "content": "<new turn>"} ]
}
```

The sample below builds requests of that shape with `cached_request` from `course/m0-cost-lab/lesson_support/` (helpers written for these lessons, not the exercise solution), reads `usage` into the three counters, their total and a hit ratio with `cache_counters`, and compares the cache-relevant part of two requests (`model`, `tools`, `system`, serialised in the order they are sent) with `prefix_fingerprint`, without calling anything. The model calls go through `cost_lab.transport.make_client` from the exercise starter, which replays the recorded `cache_write` and `cache_read` fixtures from `course/m0-cost-lab/fixtures/` instead of hitting the API; their usage numbers are synthetic. Run it from the repository root with `PYTHONPATH=course/m0-cost-lab/starter/src:course/m0-cost-lab/lesson_support/src uv run --frozen python site/samples/m0/03-1.py`.

Sample: `site/samples/m0/03-1.py`.

```python
from datetime import UTC, datetime
from pathlib import Path

from cost_lab.transport import make_client
from cost_lab_lessons import cache_counters, cached_request, prefix_fingerprint

FIXTURES = Path("course/m0-cost-lab/fixtures")
MODEL = "claude-opus-5-5"
USD_PER_MTOK = {"input": 4.00, "cache_write_5m": 5.00, "cache_read": 0.20, "output": 20.00}
SYSTEM = "\n".join(
    f"Rule {i}: quote prices in EUR with two decimals and cite the catalogue row for part family {i}."
    for i in range(1, 121)
)
TOOLS = [
    {
        "name": "get_stock",
        "description": "Units in stock for a part id.",
        "input_schema": {
            "type": "object",
            "properties": {"part": {"type": "string"}},
            "required": ["part"],
        },
    },
    {
        "name": "get_price",
        "description": "Unit price in EUR for a part id.",
        "input_schema": {
            "type": "object",
            "properties": {"part": {"type": "string"}},
            "required": ["part"],
        },
    },
]


def cost_usd(usage) -> float:
    return (
        usage.input_tokens * USD_PER_MTOK["input"]
        + (usage.cache_creation_input_tokens or 0) * USD_PER_MTOK["cache_write_5m"]
        + (usage.cache_read_input_tokens or 0) * USD_PER_MTOK["cache_read"]
        + usage.output_tokens * USD_PER_MTOK["output"]
    ) / 1_000_000


def request(history: list[dict], user_turn: str, tools: list[dict], system: str = SYSTEM) -> dict:
    return cached_request(
        model=MODEL,
        max_tokens=16000,
        system=system,
        tools=tools,
        history=history,
        user_turn=user_turn,
    )


client, transport = make_client(FIXTURES, ["cache_write", "cache_read"])
history: list[dict] = []
for turn, tools in [("Price of A1?", TOOLS), ("And how many are in stock?", list(reversed(TOOLS)))]:
    response = client.messages.create(**request(history, turn, tools))
    r = cache_counters(response.usage)
    print(
        f"total={r.total} written={r.written} read={r.read} uncached={r.uncached} "
        f"hit_ratio={r.hit_ratio:.2f} cost=${cost_usd(response.usage):.6f}"
    )
    history += [
        {"role": "user", "content": turn},
        {"role": "assistant", "content": response.content},
    ]

sent = [prefix_fingerprint(req.body) for req in transport.requests]
print("prefix identical across turns, tool order shuffled:", sent[0] == sent[1])

stamped = request(history, "Next?", TOOLS, system=f"Now: {datetime.now(UTC).isoformat()}\n{SYSTEM}")
print("prefix identical with a timestamp in system:", prefix_fingerprint(stamped) == sent[0])

operator_note = request(history, "Next?", TOOLS)
operator_note["messages"].append(
    {"role": "system", "content": "Prices for family 7 changed at 14:00 UTC."}
)
print(
    "mid-conversation system message leaves the prefix unedited:",
    prefix_fingerprint(operator_note) == sent[0],
)
```

Output, run on 2026-10-17:

```
total=1840 written=1800 read=0 uncached=40 hit_ratio=0.00 cost=$0.009260
total=1842 written=0 read=1800 uncached=42 hit_ratio=0.98 cost=$0.000628
prefix identical across turns, tool order shuffled: True
prefix identical with a timestamp in system: False
mid-conversation system message leaves the prefix unedited: True
```

The first two lines are the healthy signature. Turn 1 writes the prefix and costs more than an uncached call would ($0.009260 against 1,840 x $4 + 5 x $20 per MTok = $0.007460). Turn 2 reads it: $0.000628 against $0.007468 uncached, about 12x cheaper, with a hit ratio of 0.98. The third line shows why the tools go out in a fixed order: the second turn passed them in reverse order, as a registry built from parallel MCP connections might, and the prefix still matched. The fourth is the most common real-world miss, a timestamp at the top of the system prompt. The fifth line is not evidence of a cache hit. It shows that appending a mid-conversation system message does not edit the prefix: `prefix_fingerprint` covers `model`, `tools` and `system`, which the note leaves untouched, and the earlier messages are unchanged by construction, so the only new input is the note itself. Whether the next request actually reads the cache is something only its `usage` can confirm. Stage `03-cache-prefix` of the exercise has you write your own request builder and usage report; stage `07-live-cache-hit` checks the signature against the real API on ten requests.

What the signature should look like over a longer loop depends on where the breakpoints are. With only the system breakpoint, as above, `read` stays flat at the prefix size and `uncached` grows with the history, because the history is not cached. Add a top-level `cache_control={"type": "ephemeral"}` (automatic caching; the SDK's `messages.create` accepts it as a keyword) and the history joins the cache: from turn 2 on, `read` grows each turn, `written` is roughly the previous turn's new content, and `uncached` stays small. Three unhealthy shapes to alert on: `written` close to the full prefix on every turn (something in the prefix changes), `written` and `read` both zero (no breakpoint, or a prefix under 512 tokens), and a `read` that drops to zero after a turn that added many interleaved blocks, for example text and tool calls alternating, without a write in between (the 20-block lookback).

### Silent invalidators

The Prompt caching page's invalidation table lists what breaks which level. The ones that bite in agent code:

- **Anything time- or request-dependent before a breakpoint**: timestamps, request ids, UUIDs, a "current branch" line, a random few-shot sample. Move them after the last breakpoint or into the user turn.
- **Non-deterministic serialisation**: tools assembled from a dict or set, JSON schemas generated with unstable key order, MCP tool lists that arrive in connection order. Sort tools by name and schema keys recursively before you send them.
- **Varying tool sets per turn**: modifying tool definitions invalidates the whole cache, tools, system and messages. Declare the full set once. On current models the `inline-tools-2026-09-15` beta lets you add or withdraw tools with `tool_addition` / `tool_removal` blocks in a mid-conversation system message, leaving `tools` untouched (Mid-conversation system messages).
- **Changing effort or thinking settings mid-session**: both always invalidate cached message blocks, and on some models the tools and system caches too. `tool_choice` changes and adding or removing images invalidate message blocks as well.

### The operator channel: mid-conversation system messages

A factory often needs to tell a running agent something with system-level authority partway through: a deadline, a policy change, a remaining-budget note. Editing the top-level `system` field to do so rewrites the start of the prefix and throws away the cache for the whole history. On Opus 5.5, Sonnet 5.5, Haiku 5.5 and the Fable 5.x models, you can instead append `{"role": "system", "content": "..."}` to `messages`; the earlier prefix stays byte-identical, the next request still hits, and the instruction applies from that point on, taking precedence over the top-level `system` field. It is not available on Sonnet 5. Placement rules: it cannot be the first message, it must immediately follow a `user` turn (including one carrying tool results), and it cannot sit between a `tool_use` and its `tool_result`; elsewhere the API returns 400 (Mid-conversation system messages). Once sent, never edit or remove it, because that invalidates the cache from its position onward.

## Pitfalls seen in the wild

- **A timestamp in the system prompt.** "Today is 2026-10-17 14:03:11" at the top of `system` makes every request a fresh 1.25x write. Put the date in the user turn, or round it to the day and place it after the static block.
- **Caching a prefix below the minimum and concluding caching does not work.** A 400-token system prompt on Opus 5.5 is never cached and nothing errors. Check `cache_creation_input_tokens` on the first call; if it is zero, the prefix is too short or there is no breakpoint.
- **Default 5-minute TTL on a human-in-the-loop agent.** Turns that are minutes apart re-write the cache each time and cost more than no caching, as the six-turn example shows. Use `"ttl": "1h"` when gaps exceed five minutes and the prefix is read at least twice per hour.
- **Logging only `input_tokens`.** Dashboards built on it show cached requests as tiny and cannot see a broken cache. Log all three counters and compute the hit ratio per session.
- **Rebuilding the tool list per step to "focus" the agent.** Each change invalidates everything. Keep one stable tool set, or use mid-conversation tool changes.
- **Editing `system` to steer a long session.** Use a mid-conversation system message instead; the cached history survives.

## What interviewers ask

**How does prompt caching decide whether a request hits?**
It compares the rendered prefix, in the order tools, system, messages, up to a `cache_control` breakpoint against entries written by recent requests, and it must match exactly. Any byte change earlier in the prefix, including tool order or a timestamp, produces a different key and a miss for everything after it.

**When is the 1-hour TTL cheaper than the 5-minute one?**
When requests sharing a prefix arrive more than five minutes apart but at least twice within the hour: a 1-hour write costs 2x input against 1.25x, but a 5-minute entry that expires between requests is re-written every time. For back-to-back loops the 5-minute TTL wins because each read refreshes it at no cost.

**How do you verify caching works in production?**
Log `cache_creation_input_tokens`, `cache_read_input_tokens` and `input_tokens` per request and compute read over their sum. A healthy loop writes once and then reads the prefix every turn; repeated writes of the full prefix mean an invalidator, and zeros in both counters mean no breakpoint or a prefix below the minimum.

**How do you inject an instruction into a long-running cached conversation?**
Append a `role: "system"` message after the latest user turn instead of editing the top-level system prompt, on models that support it. The cached prefix stays identical, so the next request still reads it, and only the new message is billed as fresh input.

**What is the relationship between Anthropic's prompt caching and vLLM's prefix caching?**
Both reuse computed attention state for an exact token prefix, and vLLM documents its version as hashing KV blocks chained through all earlier tokens. Anthropic does not document its implementation, so the API contract (exact prefix, breakpoints, TTL, minimum length) is what you design against.

## Sources

- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), checked 2026-10-17
- [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-10-17
- [Mid-conversation system messages and tool changes](https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages), checked 2026-10-17
- [vLLM design, Automatic Prefix Caching](https://docs.vllm.ai/en/stable/design/prefix_caching/), checked 2026-10-17
- Course code (repository files, not web sources): the lesson helpers in `course/m0-cost-lab/lesson_support/src/cost_lab_lessons/` and the recorded transport in `course/m0-cost-lab/starter/src/cost_lab/transport.py`
