from serving_lab_lessons.capacity import stream_metrics, throughput

streams = {
    "first in": ([0.40, 0.45, 0.50, 0.55, 0.60], 0.62),
    "queued": ([2.10, 2.15, 2.20, 2.25, 2.30], 2.32),
    "one token": ([0.38], 0.40),
}
results = {name: stream_metrics(times, done) for name, (times, done) in streams.items()}
for name, m in results.items():
    tps = "None" if m["tps"] is None else f"{m['tps']:.1f}"
    print(
        f"{name:<10} ttft {m['ttft_ms']:7.1f} ms  tps {tps:>5}  latency {m['latency_ms']:7.1f} ms"
    )

wall_s = max(done for _, done in streams.values())
tokens = [m["tokens"] for m in results.values()]
print(f"throughput {throughput(tokens, wall_s):.2f} output tokens/s over {wall_s} s")
