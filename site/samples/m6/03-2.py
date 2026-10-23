from serving_lab_lessons.local_runs import local_route_latencies, local_run_summary

lab = "course/m6-serving-lab/fixtures/"
s = local_run_summary(lab + "live_local_model_run.json")
print(f"{s['model']} on {s['runtime']}, {s['machine_class']}")
print(f"{s['requests']} requests at concurrency {s['concurrency']}, max_tokens {s['max_tokens']}")
print(f"TTFT ms p50/p90/p99: {s['ttft_ms']['p50']} / {s['ttft_ms']['p90']} / {s['ttft_ms']['p99']}")
print(f"requests with TTFT >= p50: at least {s['at_or_above_p50']} of {s['requests']}")
print(f"output tokens ~{s['output_tokens']}, {s['tokens_per_request']:.1f} per request")
print(f"decode at p50 TPS {s['tps_p50']}: {s['decode_s_at_p50']:.2f} s per request")
print(f"TTFT p50 + decode: {s['ttft_plus_decode_s']:.2f} s")
print(
    f"wall {s['wall_s']} s over {s['rounds']} rounds of {s['concurrency']}: {s['seconds_per_round']:.2f} s per round"
)

stage08 = local_route_latencies(lab + "live_gateway_run.json")
print("stage 08 local answers, one at a time (ms, tokens):", stage08)
