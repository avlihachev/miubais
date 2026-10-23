import math
from collections.abc import Sequence

SECONDS_PER_HOUR = 3600


def nearest_rank(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def stream_metrics(token_times_s: Sequence[float], done_s: float) -> dict:
    tokens = len(token_times_s)
    if tokens == 0:
        return {"tokens": 0, "ttft_ms": None, "tps": None, "latency_ms": done_s * 1000}
    span = token_times_s[-1] - token_times_s[0]
    return {
        "tokens": tokens,
        "ttft_ms": token_times_s[0] * 1000,
        "tps": tokens / span if span > 0 else None,
        "latency_ms": done_s * 1000,
    }


def throughput(output_tokens: Sequence[int], wall_s: float) -> float:
    return sum(output_tokens) / wall_s


def usd_per_mtok_out(gpu_usd_per_hour: float, run_s: float, output_tokens: int) -> float:
    run_usd = gpu_usd_per_hour / SECONDS_PER_HOUR * run_s
    return run_usd / (output_tokens / 1e6)
