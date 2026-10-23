# Benchmark: {model} on {gpu}

## Setup

| item | value |
| --- | --- |
| GPU | {gpu} at {gpu_usd_per_hour:.2f} USD/h |
| model | {model} |
| quantisation | {quantisation} |
| tensor parallel size | {tp_size} |
| max model length | {max_model_len} |

## Load

{n} requests, {failed} failed, over {wall_s:.1f} s of load; {run_s:.1f} s of GPU time billed.

## Results

| metric | value |
| --- | --- |
| TTFT p50 (ms) | {p50_ttft_ms:.1f} |
| TTFT p90 (ms) | {p90_ttft_ms:.1f} |
| TTFT p99 (ms) | {p99_ttft_ms:.1f} |
| TPS p50 (tokens/s per request) | {p50_tps:.1f} |
| throughput (output tokens/s) | {throughput_tps:.1f} |
| output tokens | {output_tokens} |

## Cost model

cost per million output tokens = (GPU USD/h ÷ 3600 × run seconds) ÷ (output tokens / 1e6)

= ({gpu_usd_per_hour:.2f} ÷ 3600 × {run_s:.1f}) ÷ ({output_tokens} / 1e6) = {usd_per_mtok_out:.2f} USD

| source | USD per million output tokens |
| --- | --- |
| this run | {usd_per_mtok_out:.2f} |
| API list price | {api_price} |

At this rate the GPU produces {output_tokens_per_hour:,.0f} output tokens per hour, and one request
at this mix of prompt and output lengths costs {usd_per_request:.4g} USD.

## Caveats

- A single run: with no repeats there is no spread to judge the numbers against.
- Cold cache: the prefix cache started empty; traffic that shares system prompts reuses more of it
  and gets a lower TTFT.
- No SLA: the run reports percentiles but sets no latency target, so its cost per token compares
  only with setups that meet the same TTFT and TPS.
- Full utilisation: the cost assumes the GPU works through every billed second; idle hours between
  bursts raise the real cost per token.
