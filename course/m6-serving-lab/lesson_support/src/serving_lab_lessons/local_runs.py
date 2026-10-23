import json
import math
from pathlib import Path


def local_run_summary(path) -> dict:
    record = json.loads(Path(path).read_text())
    n = record["requests"] - record["failed"]
    tokens = round(record["throughput_tps"] * record["wall_s"])
    per_request = tokens / n
    rounds = math.ceil(n / record["concurrency"])
    decode_s = per_request / record["tps_p50"]
    return {
        "model": record["model"],
        "runtime": record["runtime"],
        "machine_class": record["machine_class"],
        "requests": n,
        "concurrency": record["concurrency"],
        "max_tokens": record["max_tokens"],
        "ttft_ms": record["ttft_ms"],
        "tps_p50": record["tps_p50"],
        "throughput_tps": record["throughput_tps"],
        "wall_s": record["wall_s"],
        "output_tokens": tokens,
        "tokens_per_request": per_request,
        "rounds": rounds,
        "seconds_per_round": record["wall_s"] / rounds,
        "decode_s_at_p50": decode_s,
        "ttft_plus_decode_s": record["ttft_ms"]["p50"] / 1000 + decode_s,
        "at_or_above_p50": n - math.ceil(0.5 * n) + 1,
    }


def local_route_latencies(path, route: str = "ollama") -> list[tuple[float, int]]:
    record = json.loads(Path(path).read_text())
    return [
        (p["latency_ms"], p["tokens_out"])
        for p in record["prompts"]
        if p["route"] == route and p["ok"]
    ]
