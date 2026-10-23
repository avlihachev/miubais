USD_PER_MTOK = {
    "input": 4.00,
    "output": 20.00,
    "cache_read": 0.20,
    "write_5m": 5.00,
    "write_1h": 8.00,
}
CONVERSATIONS = 2_000 * 30
TURNS, PREFIX, USER, ASSISTANT = 4, 6_000, 100, 300
LONG_GAP_SHARE = 0.4

history = sum((k - 1) * (USER + ASSISTANT) + USER for k in range(1, TURNS + 1))
fixed = (history * USD_PER_MTOK["input"] + TURNS * ASSISTANT * USD_PER_MTOK["output"]) / 1e6


def prefix_usd(writes: int, reads: int, write_price: float) -> float:
    return (writes * write_price + reads * USD_PER_MTOK["cache_read"]) * PREFIX / 1e6


no_cache = TURNS * PREFIX * USD_PER_MTOK["input"] / 1e6 + fixed
hit_5m = prefix_usd(1, TURNS - 1, USD_PER_MTOK["write_5m"]) + fixed
miss_5m = prefix_usd(TURNS, 0, USD_PER_MTOK["write_5m"]) + fixed
hit_1h = prefix_usd(1, TURNS - 1, USD_PER_MTOK["write_1h"]) + fixed

print(f"history input per conversation: {history} tokens")
for name, usd in [
    ("no cache", no_cache),
    ("5m, every gap short", hit_5m),
    ("5m, every gap long", miss_5m),
    ("1h, every gap under 1h", hit_1h),
    ("5m, 40% long gaps", (1 - LONG_GAP_SHARE) * hit_5m + LONG_GAP_SHARE * miss_5m),
    ("5m or 1h by gap", (1 - LONG_GAP_SHARE) * hit_5m + LONG_GAP_SHARE * hit_1h),
]:
    print(f"{name:<24} ${usd:.5f}/conversation  ${usd * CONVERSATIONS:,.0f}/month")
