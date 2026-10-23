# Serving lab

You build `serving_lab`, the measuring and platform side of serving open models: a load generator
that measures time to first token (TTFT) and tokens per second (TPS) against an OpenAI-compatible
endpoint, a live run against a small local model, Kubernetes manifests for a vLLM production stack
validated offline, an autoscaling policy simulated on replayed metrics, a gateway that routes
between a local model and the Claude API, a cloud-GPU benchmark report with a cost model, and a
serving plan for a stated scenario.

There is no GPU in this course. Every offline stage runs against `serving_lab.fake_server`, a
threaded fake of a vLLM server whose token rate and queueing delay you set, so the tests can check
your numbers against known answers. Stages 02 and 08 run against a real local model.

`serving_lab/types.py` is given and shared by every stage (`RequestResult`, `Summary`, `RunResult`,
`Route`, `RouteStats`, `ChatRequest`, `ChatResult`, `ScalePolicy`, `Sample`, `ScaleDecision`,
`BenchmarkInput`, `BenchmarkReport`, `Validation`, `CheckItem`). `serving_lab/fake_server.py` and
`serving_lab/BENCHMARK_TEMPLATE.md` are given too. Write the stage modules against them; do not
change any of them.

## How to run

Run every command below in a terminal at the root of your clone of this repository, after a one-time `uv sync` there; `uv run miubais doctor` lists what this machine has.

```
uv run miubais start m6-serving-lab
```

This copies `course/m6-serving-lab/starter/` to `workspace/m6-serving-lab/` at the repo root. That copy is yours: the stubs under `workspace/m6-serving-lab/src/serving_lab/` raise `NotImplementedError` until you fill them in, and the judgment stage asks for a file in the workspace root, named in its description below. The tests stay in `course/m6-serving-lab/tests/` and import your package from the workspace. `start --force` replaces the workspace with a fresh copy.

```
uv run miubais check m6-serving-lab
```

Runs the stages in order and stops at the first failure, printing its pytest output, so stage 02 waits for stage 01. `--stage <stage id>` runs one stage and `--all` keeps going past a failure. A stage whose `requires` (in `stages.yaml`) are missing on your machine is skipped, not failed. Results are kept in `~/.miubais/progress.json`; `uv run miubais reset m6-serving-lab` forgets them (`--all` for every exercise), and `start --force` does the same along with the fresh copy.

```
uv run miubais hint m6-serving-lab
```

Takes the last stage `check` saw fail, its test output and your diff against the starter, and asks the tutor on your Claude Code login for a nudge of under 90 words that is checked not to hand you the solution. If the model cannot be reached, you get a pointer to the failing test instead.

The **Run check** and **Hint** buttons on the site's exercise page do the same while `uv run miubais serve` is running, and share the progress file with the terminal.

## The fake server (given)

`FakeOpenAIServer(*, tokens_per_second=50, queue_delay_ms=0, first_token_ms=20, max_concurrent=4,
model="fake-7b", fail_after_tokens=None, fail_status=None, healthy=True, health_delay_ms=0)` is a
context manager (or call `.start()` and `.stop()`) on an ephemeral port. `.url` is the root
(`http://127.0.0.1:<port>`), `.base_url` is `.url + "/v1"`, the shape an OpenAI client expects. It
serves:

- `GET /health` (200, or 503 with `healthy=False`), `GET /v1/models` (one model, `model`),
  `GET /metrics` in Prometheus text with vLLM's names: `vllm:num_requests_running`, `vllm:num_requests_waiting`,
  `vllm:time_to_first_token_seconds_count`/`_sum`, `vllm:e2e_request_latency_seconds_count`/`_sum`,
  `vllm:prefix_cache_hits_total`, `vllm:prefix_cache_queries_total`.
- `POST /v1/chat/completions`, 404 for any other model name. Every request first waits
  `queue_delay_ms` and then for one of `max_concurrent` slots (counted in
  `vllm:num_requests_waiting` meanwhile). The first content token comes `first_token_ms` after the
  slot, then one token every `1 / tokens_per_second` seconds, `max_tokens` tokens in all (16 when
  absent): `"tok1"`, `" tok2"`, `" tok3"`, ...
- With `"stream": true` the response is server-sent events: lines `data: {json}` separated by blank
  lines. The first chunk is role-only (`choices[0].delta == {"role": "assistant"}`), then one chunk
  per token with `choices[0].delta.content`, then a chunk with `finish_reason: "length"` and an empty
  delta, then, when `stream_options.include_usage` is true, a chunk with `choices: []` and `usage`,
  then `data: [DONE]`. Without `stream` the response is one `chat.completion` JSON with `usage`.
  In `usage`, `prompt_tokens` is the number of words in the prompt.
- `fail_after_tokens=n` sends `n` content chunks and closes the connection: no finish chunk, no
  `[DONE]`.
- `fail_status=503` answers every chat completion with that status and a JSON error;
  `healthy=False` makes `/health` answer 503; `health_delay_ms` delays `/health`. All three are
  attributes read on every request, so a test can flip them while the server runs.

## Stages

1. `01-load-generator`: `loadgen.run(base_url, *, model, prompts, concurrency, max_tokens,
   timeout_s=60) -> RunResult(requests, summary)` sends one streaming chat completion per prompt
   (`messages=[{"role": "user", "content": prompt}]`, `stream: true`,
   `stream_options: {"include_usage": true}`) to `base_url + "/chat/completions"` with an
   `httpx2.AsyncClient`, at most `concurrency` in flight (an `asyncio.Semaphore`).
   `loadgen.run_async` is the same coroutine for callers already inside an event loop. Each request
   gives `RequestResult(prompt_id, ttft_ms, tps, latency_ms, output_tokens, ok, error)`, with
   `prompt_id` the prompt's index and the clock started when the request is sent:
   - an output token is a chunk whose `choices[*].delta.content` is non-empty. A role-only delta,
     the finish chunk, the usage chunk and the `[DONE]` sentinel are not tokens.
   - `ttft_ms` is send to the first token (`None` when there was none); `latency_ms` is send to
     `[DONE]` (or to the failure); `output_tokens` counts the tokens; `tps` is
     `output_tokens / (last token time - first token time)`, `None` when that span is zero.
   - `ok` is true only when `[DONE]` arrived. A stream that ends without it, or a connection reset
     mid-stream, is `ok=False, error="stream closed"`, never a short success; a non-200 status is
     `error="HTTP <status>"`; a timeout is `error="timeout"`.

   `loadgen.percentile(values, p)` is nearest-rank: sort ascending, take the value at rank
   `ceil(p / 100 * n)` (1-based, at least 1); an empty list gives `0.0`.
   `loadgen.summarise(requests, wall_s) -> Summary(n, failed, p50_ttft_ms, p90_ttft_ms,
   p99_ttft_ms, p50_tps, throughput_tps, wall_s)` takes percentiles over the successful requests
   only (skipping `None`); `throughput_tps` is the successful requests' total output tokens divided
   by the run's wall time. `run` measures `wall_s` from the first send to the last result.
   `loadgen.to_markdown(summary)` returns a two-column table that starts with
   `| metric | value |` and has the rows `requests`, `failed`, `TTFT p50 (ms)`, `TTFT p90 (ms)`,
   `TTFT p99 (ms)`, `TPS p50 (tokens/s per request)`, `throughput (output tokens/s)` and
   `wall time (s)`, times to one decimal and the wall time to two.
   `loadgen.main(argv)` is the CLI: `python -m serving_lab.loadgen --base-url ... --model ...
   --concurrency 8 --requests 32 --max-tokens 64 [--timeout 60] [--out run.json]` generates
   `--requests` short prompts, prints the table, writes the `RunResult` as JSON to `--out`, and
   returns 1 when any request failed, else 0.

   The tests check TTFT against `queue_delay_ms + first_token_ms` and TPS against
   `tokens_per_second` within 20% at concurrency 1, that eight requests against two server slots
   raise p90 TTFT well above a run within the slots (and that the server reports waiting requests
   meanwhile), that the role-only delta and `[DONE]` are not tokens, that a stream closed early is a
   failure, the percentiles on known lists, the summary, the table and the CLI.
2. `02-local-model` (live, Ollama): the load generator against `qwen3.5:0.8b` on Ollama's
   OpenAI-compatible endpoint, `http://localhost:11434/v1`. The stage needs one change to your
   stage 01 code: merge `extra_body` (already in the signatures of `run` and `run_async`) into the
   request JSON. `qwen3.5:0.8b` is a reasoning model, and with the default settings it spends a
   48-token budget on `delta.reasoning` chunks that carry an empty `delta.content`, so no token
   counts and TTFT is `None`. The test sends `{"reasoning_effort": "none"}` through `extra_body`.
   The test skips with `needs ollama model qwen3.5:0.8b: run ollama pull qwen3.5:0.8b` when
   `ollama list` does not show the model. It sends 8 short prompts at concurrency 2 with
   `max_tokens` 48 and requires every request to succeed, a p50 TPS above 5 and a p90 TTFT under
   10,000 ms. It writes the aggregate to `runs/live-<date>.json` in your workspace, without the
   prompt texts. The numbers depend on the machine: the committed reference run, with the
   machine class and the percentiles, is `fixtures/live_local_model_run.json`.
3. `03-k8s-manifests` (helm, kubeconform): code in `serving_lab/k8s.py`; YAML in your workspace's
   `k8s/` directory. The chart is vendored at `fixtures/k8s/vllm-stack-0.1.13/` (vLLM production
   stack `vllm/vllm-stack` 0.1.13, Apache-2.0; see its `VENDORED.md`), and the JSON schemas
   kubeconform needs are vendored at `fixtures/k8s-schemas/`. Nothing in this stage touches the
   network: the tests run with `HTTPS_PROXY=http://127.0.0.1:9`. Call `helm` and `kubeconform` by
   name from PATH.
   - `render(chart_dir, values_path, *, release="miubais") -> str` runs
     `helm template <release> <chart_dir> --values <values_path> --skip-tests` and returns the
     manifests. Point Helm's repository config and cache at a fresh temporary directory
     (`--repository-config`/`--repository-cache` or `HELM_REPOSITORY_CONFIG`/`HELM_REPOSITORY_CACHE`),
     so your own `helm repo` setup can never leak in. Run no other Helm subcommand. On failure raise
     `RuntimeError` carrying Helm's stderr.
   - `validate(manifests, *, schemas_dir, kubernetes_version="1.31.0", strict=True) -> Validation`
     pipes the manifests to `kubeconform -summary -output json` (plus `-strict` when `strict`) with
     `-kubernetes-version` and exactly two `-schema-location`s under `schemas_dir`:
     `schemas_dir / CORE_SCHEMAS` for built-in kinds and `schemas_dir / CRD_SCHEMAS` for CRDs (both
     patterns are in the starter). No `default` location, no URL, and no `-ignore-missing-schemas`:
     a kind without a schema is an error. `ok` is true only when kubeconform exits 0 and at least
     one resource validated; `errors` holds one string per failing resource naming its kind, name
     and the failing path; `summary` gives the valid/invalid/errors/skipped counts. `strict=False`
     relaxes only the built-in kinds: the vendored CRD schemas exist in a strict form only, so an
     unknown field in an `InferencePool` or a `ScaledObject` fails either way.
   - `checklist(manifests) -> list[CheckItem]` returns one item per name in `CHECKS`, in that
     order, checked on every vLLM container (an image whose name ends in `vllm-openai`, or a
     `vllm serve` command) and its Deployment; `detail` says what is wrong:
     - `gpu_request`: requests at least one `nvidia.com/gpu`.
     - `runtime_class`: the pod sets `runtimeClassName: nvidia`.
     - `readiness_probe`: an HTTP readiness probe on `/health`.
     - `pdb`: a `PodDisruptionBudget` whose selector matches the pod labels.
     - `resource_limits`: a memory limit.
     - `model_pvc`: the model cache is mounted from a `PersistentVolumeClaim`.
     - `hf_token_secret`: `HF_TOKEN` (or `HUGGING_FACE_HUB_TOKEN`) is set and comes from a
       `secretKeyRef`, never an inline `value`, and no rendered `Secret` carries an `hf_token*` key
       (that means the token was written into the values file).
     - `max_model_len`: `--max-model-len` is in the vLLM command or args.

     With no vLLM Deployment, every item fails.
   - `k8s/values-local.yaml` is given: the chart's minimal example for one small model. Do not edit
     it; the checklist must fail it for `runtime_class`, `pdb`, `resource_limits`, `model_pvc`,
     `hf_token_secret` and `max_model_len`.
   - Write `k8s/values-prod.yaml` for one model on `vllm/vllm-openai` with `requestGPU: 1` that
     passes every check, rendered with release `miubais`. Keep `kube-prometheus-stack`,
     `prometheus-adapter` and `k8s-aibom` disabled explicitly. The HF token lives in a Secret you
     create outside the chart (`hf_token: {secretName, secretKey}`).
   - Write `k8s/inferencepool.yaml` (`inference.networking.k8s.io/v1` `InferencePool` selecting the
     prod vLLM pods on their container port, with an `endpointPickerRef`), `k8s/gateway.yaml`
     (`gateway.networking.k8s.io/v1` `Gateway`), `k8s/httproute.yaml` (an `HTTPRoute` attached to
     that Gateway whose backendRef is the InferencePool, group `inference.networking.k8s.io`) and
     `k8s/scaledobject.yaml` (`keda.sh/v1alpha1` `ScaledObject` targeting the rendered vLLM
     Deployment, with a `prometheus` trigger whose metadata has `serverAddress`, a `query` on
     `vllm:num_requests_waiting`, `threshold` and `activationThreshold`). Each must validate, and
     the tests check that the names and labels line up with the prod render.

   Pitfalls: KEDA trigger metadata values are strings (`threshold: "4"`); a `ReadWriteOnce` PVC
   shared by several replicas cannot schedule them on different nodes; with the chart's own KEDA
   off the Deployment keeps its `replicas`, which a `helm upgrade` resets under the HPA KEDA
   created; an inline token in a values file ends up base64-encoded in a rendered Secret, which
   anyone who can read Secrets can decode.
4. `04-autoscaling-policy` (kubeconform): code in `serving_lab/autoscale.py`.
   Its tests call your stage 03 `k8s.validate`, which needs kubeconform only; write it even if
   stage 03 was skipped for lack of Helm.
   `ScalePolicy(min_replicas, max_replicas, target_waiting, activation, stabilisation_s,
   cooldown_s)` mirrors a KEDA `prometheus` trigger on `vllm:num_requests_waiting` (`METRIC` in
   the starter): `target_waiting` is the trigger's `threshold`, the waiting requests one replica
   should carry, and `activation` is its `activationThreshold`.
   - `desired_replicas(policy, waiting) -> int`: when `min_replicas` is 0 and
     `waiting <= activation`, the trigger is inactive and the answer is 0. Otherwise it is
     `ceil(waiting / target_waiting)` clamped to `max(min_replicas, 1)` below and `max_replicas`
     above. The activation threshold only decides between zero and one replica, as in KEDA; with
     `min_replicas >= 1` it has no effect.
   - `simulate(policy, series, *, replicas0) -> list[ScaleDecision]` replays the
     `Sample(t_s, waiting, running)`s in time order, starting from `replicas0` replicas, and
     returns one `ScaleDecision(t_s, replicas, reason)` per change, in time order; an empty list
     means the count never changed. At each sample time `t`:
     - If `replicas0` is outside `[min_replicas, max_replicas]`, the first decision, at the first
       sample's time, clamps it; its reason starts with `clamp`.
     - Scale up: once `t - <first sample's t_s> >= stabilisation_s`, take the samples with `t_s` in
       `[t - stabilisation_s, t]` and the lowest `desired_replicas` among them. If it is above the
       current count, scale to it; the reason starts with `up`. With `stabilisation_s = 0` the
       window is the sample itself.
     - Otherwise scale down: once `t - <last change, or the first sample's t_s> >= cooldown_s`,
       take the samples in `[t - cooldown_s, t]` and the highest `desired_replicas` among them. If
       it is below the current count, scale to it; the reason starts with `down`.

     This is the HPA's stabilisation: the lowest recommendation in the window when going up and
     the highest when going down, so one high sample never adds a replica and one quiet minute
     never removes one.
   - `to_scaledobject(policy, *, deployment, prometheus_url, model=None) -> dict` returns the
     `keda.sh/v1alpha1` `ScaledObject` for the policy: `metadata.name` and `scaleTargetRef.name`
     are `deployment` (`apiVersion: apps/v1`, `kind: Deployment`); `minReplicaCount`,
     `maxReplicaCount`, `cooldownPeriod: cooldown_s`;
     `advanced.horizontalPodAutoscalerConfig.behavior` with
     `scaleUp.stabilizationWindowSeconds: stabilisation_s` and
     `scaleDown.stabilizationWindowSeconds: cooldown_s`; and one `prometheus` trigger whose
     `metadata` is exactly `serverAddress`, `query`, `threshold` and `activationThreshold`. The
     query is `sum(vllm:num_requests_waiting)`, or `sum(vllm:num_requests_waiting{model_name="<model>"})`
     when `model` is given; the thresholds are strings formatted with `f"{value:g}"` (`4.0` gives
     `"4"`). The tests dump the dict with `yaml.safe_dump` and validate it with your stage 03
     `k8s.validate` against `fixtures/k8s-schemas/`.
   - `fixtures/k8s/metrics-series.json` is an invented day for one replica, sampled every 60 s
     from midnight (`samples: [{t_s, waiting, running}]`, `synthetic: true`), with a one-sample
     blip at 10:30 and a lunch spike from 12:00 to 12:59. With min 1, max 4, threshold 4,
     activation 1, a 120 s stabilisation window and a 300 s cooldown, the tests expect the blip to
     change nothing and the day to give exactly two decisions: up to 3 at 12:02 and down to 1 at
     13:05. They also check the bounds, the windows and the cooldown on short series of their own.

   Pitfalls: KEDA's `cooldownPeriod` only covers the step from one replica to zero; scaling down
   between other counts follows the HPA's `scaleDown.stabilizationWindowSeconds` (300 s when
   unset), which is why the policy's cooldown sets both. The replay is open-loop: the series was
   recorded on one replica, so its waiting count does not fall when the simulation adds replicas,
   while a real queue drains. A new vLLM replica needs minutes to pull its image and load the
   weights, so a scale-up decided at 12:02 serves traffic some minutes later.
5. `05-gateway-routing`: code in `serving_lab/gateway.py`.
   `Gateway(routes, *, prefer="local", query_fn=None, timeout_s=30.0, health_path="/health",
   extra_body=None)`
   routes `ChatRequest(prompt, require, max_tokens)`s between the first route of kind `local` and
   the first of kind `api` in `routes`, each a
   `Route(name, kind, model, base_url, max_tokens, price_per_mtok_in, price_per_mtok_out)`.
   Duplicate route names raise `ValueError`. The routing rules follow M3's router
   ([M3 lesson 05](/m3/05-routing-and-fallback/)).
   - Order: `require="local"` allows only the local route and `require="api"` only the API route;
     `require="any"` tries the `prefer` route first and the other second. A request that no
     configured route may serve raises `ValueError`.
   - Before trying the local route, the gateway skips it when the prompt does not fit,
     `ceil(len(prompt) / 4) + max_tokens > route.max_tokens` (the route's `max_tokens` is its
     context length; four characters per token is the estimate), or when it is unhealthy:
     `GET <root><health_path>` does not answer 200 within `HEALTH_TIMEOUT_S` (1 s), where `<root>`
     is `base_url` without its trailing `/v1`. The probe runs on every request.
   - Local call: `POST <base_url>/chat/completions` with `httpx2`, body
     `{"model", "messages": [{"role": "user", "content": prompt}], "max_tokens"}` with the
     `extra_body` dict merged in (stage 08 sends `{"reasoning_effort": "none"}` to Ollama, as stage
     02 does), not streaming, timeout `timeout_s`. The text is `choices[0].message.content`, `tokens_out` is
     `usage.completion_tokens`, and the cost is
     `(prompt_tokens * price_per_mtok_in + completion_tokens * price_per_mtok_out) / 1e6` from
     `usage`.
   - API call: `query_fn(prompt=prompt, options=ClaudeAgentOptions(model=route.model, tools=[],
     max_turns=1, max_budget_usd=0.05, setting_sources=[], strict_mcp_config=True))`
     (`MAX_TURNS` and `MAX_BUDGET_USD` in the starter), with
     `claude_agent_sdk.query` when `query_fn` is `None`; the tests pass
     `harnesskit.testing.scripted_query`. The text joins the `TextBlock`s of the
     `AssistantMessage`s, `tokens_out` is the `ResultMessage`'s `usage["output_tokens"]`, and the
     cost is its `total_cost_usd`, or the route's prices applied to its `usage` when that is
     `None`. A `ResultMessage` with `is_error`, no `ResultMessage` at all, or a `ClaudeSDKError` is
     a failed attempt, and its cost still counts. Without `setting_sources=[]` the SDK loads the
     user's and project's settings, CLAUDE.md files and MCP servers into the call.
   - Fallback: a local 5xx, timeout or connection error moves on to the next allowed route; a 4xx
     does not, since paying for the API will not fix a wrong model name. With `prefer="api"` an API
     failure moves on to the local route.
   - `require="local"` never reaches the API. When the local route is unhealthy, too small, down or
     failing, `chat` returns `ok=False` with `route` set to the local route's name, an `error`,
     empty `text` and zero cost.
   - `chat` returns `ChatResult(route, text, latency_ms, cost_usd, tokens_out)`: `route` names the
     route that answered (on failure, the last route tried); `latency_ms` runs from the call to the
     return, a failed first attempt included; `cost_usd` adds up every attempt. When no allowed
     route answers, `ok=False` and `error` lists `<route name>: <reason>` for each route, joined by
     `"; "` (`local: HTTP 502; claude: error_during_execution`).
   - `stats()` returns one `RouteStats(name, requests, failures, p50_latency_ms, cost_usd)` per
     route, in `routes` order. Every attempt counts as a request and a failed one also as a
     failure; a skipped route counts nothing, except that a request left with no route to try
     counts as a request and a failure of its first allowed route. `p50_latency_ms` is the
     nearest-rank median (stage 01's `percentile`) of the route's successful attempts, 0.0 with
     none.
   - `to_markdown()` returns the header
     `| route | kind | model | requests | failures | p50 latency (ms) | cost (USD) |`, a separator
     row, one row per route (latency to one decimal, cost to six) and a last row
     `| total | | | <requests> | <failures> | | <cost> |`.

   The tests run the local route against the fake server (`fail_status`, `healthy`,
   `health_delay_ms` and `queue_delay_ms` provoke each failure) and the API route against
   `scripted_query`, and check that no `require: local` prompt reaches the API.

   Pitfalls: Ollama has no `/health` (it answers 404), so pass `health_path="/"` for an Ollama
   route; vLLM and llama.cpp serve `/health`. A fallback after a timeout costs the user
   `timeout_s` before the API starts, so `timeout_s` also sets the worst-case latency of a
   fallback. `chat` runs the Agent SDK with `asyncio.run`, which fails inside an already running
   event loop. Four characters per token underestimates code and non-English text: a prompt the
   estimate admits can still get a 400 for exceeding the context, and since a 4xx does not fall
   back, that `any` request fails.
6. `06-benchmark-report`: code in `serving_lab/benchmark.py`; the report's layout is given in
   `serving_lab/BENCHMARK_TEMPLATE.md` (`TEMPLATE` in the starter).
   - `from_inputs(inp: BenchmarkInput) -> BenchmarkReport` with
     `output_tokens = round(summary.throughput_tps * summary.wall_s)`,
     `output_tokens_per_hour = output_tokens / run_s * 3600`,
     `usd_per_mtok_out = (gpu_usd_per_hour / 3600 * run_s) / (output_tokens / 1e6)`,
     `usd_per_request` the same run cost divided by the successful requests (`n - failed`),
     `api_usd_per_mtok_out` copied from the input and `input` the input itself. `run_s` is the GPU
     time you pay for: it can be longer than the load's `wall_s` (model load, idle time) but not
     shorter. Raise `ValueError` for a GPU price or `run_s` that is not positive, for
     `run_s < summary.wall_s`, and for a run with no output tokens or no successful request.
   - The GPU price is an input and never a constant in the module; the tests vary it.
   - `render(report) -> str` fills the template with `str.format_map`. Its placeholders are the
     fields of `BenchmarkInput`, `Summary` and `BenchmarkReport`, plus `api_price`: the API price
     to two decimals, or `not given`. The template's format specs set every precision.
   - `main(argv) -> int`, run as `python -m serving_lab.benchmark --input run.json --gpu H100
     --usd-per-hour 2.5 [--run-s S] [--api-usd-per-mtok-out P] [--model M] [--quantisation Q]
     [--tp-size N] [--max-model-len N] [--out BENCHMARK.md]`. `--input` is a JSON file with a
     `summary` object (the shape `loadgen --out` writes) and a `setup` object with `model`,
     `quantisation`, `tp_size` and `max_model_len`, which the flags override; a value missing from
     both is a usage error (exit 2, as argparse gives). `--gpu` and `--usd-per-hour` are required;
     `--run-s` defaults to the summary's `wall_s`. It prints the report, also writes it to `--out`
     when given, and returns 0.
   - `fixtures/benchmarks/sample-run.json` is an invented vLLM run, marked `synthetic`: 64
     requests at concurrency 16 with 256 output tokens each, shaped like Qwen3.5-27B in FP8 on one
     H100. Its token counts, wall time, TPS and throughput agree with each other, and the tests
     render it through the CLI.

   Pitfalls: the cost holds only at the measured concurrency, since the same GPU serving one
   stream at a time produces a fraction of the tokens per hour. An API list price covers input
   tokens separately and costs nothing while idle, whereas the self-hosted figure assumes the GPU
   is busy for every billed second. A result for one GPU type and quantisation does not carry over
   to another.
7. `07-serving-plan` (judgment): write `SERVING_PLAN.md` in your workspace root for the scenario
   in the next section, with:
   - a Markdown table with the columns `| workload | where | model | why |` and one row for each of
     the four workloads: agent coding tickets, support chat, embeddings and retrieval, judge and
     evals. `where` names one of `local`, `self-hosted vLLM` or `API`; `model` names a model;
     `why` gives the reason in five words or more;
   - a `## Capacity` section with the tokens per day and the number of replicas, written as
     `<n> tokens per day` and `<n> replicas`, and the arithmetic shown
     (`3 × 400 = 1,200`);
   - a `## Risks` section with at least three bullets of eight words or more.

   The tests find each row by its workload name and compare its `where` with a key of the
   placements that fit the scenario (`tests/KEY.yaml`, plaintext: read it only to check your own
   plan); 3 of the 4 must agree. They check the capacity section for a tokens-per-day figure, a
   replica count and an arithmetic line, and count the risks.

   Pitfalls: a `where` cell that names two placements ("local or API") counts as none; pick one
   and give the alternative in `why`. A heading such as `## Residual risks` or `## Sizing` is not
   read as `## Risks` or `## Capacity`.
8. `08-live-gateway` (live, Ollama and Claude): your stage 05 gateway over the real local model
   and the real Claude API. The test builds
   `Gateway([Route("ollama", "local", "qwen3.5:0.8b", "http://localhost:11434/v1", 1024, 0.0, 0.0),
   Route("claude", "api", "claude-opus-5-5", None, 200_000, 4.0, 20.0)], prefer="local",
   timeout_s=120, health_path="/", extra_body={"reasoning_effort": "none"})` and sends six
   prompts with `max_tokens` 128: two with `require="local"`, two with `require="api"` and two
   with `require="any"`, one of these a 4,500-character log that does not fit the local route's
   1,024 tokens. `max_tokens` bounds only the local route: the Agent SDK call takes no output
   limit and is bounded by `max_budget_usd=0.05` instead, so an API answer can run past 128 tokens.
   - It asserts the routing: the `local` prompts answered by `ollama`, the `api` prompts by
     `claude`, the short `any` prompt by `ollama` and the long one by `claude`. Every result is
     `ok` with a non-empty text or a failure with an `error`, no `require="local"` prompt is
     answered by `claude`, and the six cost at most 0.20 USD together.
   - It writes, per prompt, the route, `ok`, latency, cost and output tokens, then the per-route
     stats and the total cost, to `runs/live-gateway-<date>.json` in your workspace, without
     prompt or answer texts, and prints `to_markdown()`.
   - It skips with the stage 02 message when `ollama list` does not show the model, and with
     `needs claude-auth` when Claude Code is not logged in. The offline tests replay the six
     prompts against the fake server and `scripted_query` and check the routes, that the `local`
     prompts fail with an `error` and never reach the API when the local port is closed, and that
     `extra_body` reaches the local request.
   - The committed reference run is `fixtures/live_gateway_run.json`: six results, all on the
     expected route, 0.056779 USD in all, spent on the three API calls.

   Pitfalls: the local route's 1,024 tokens is a routing limit chosen so that one prompt overflows
   it, not Ollama's context window. Without `extra_body`, `qwen3.5:0.8b` spends its `max_tokens`
   on reasoning and returns an empty `content`, which the test reports as `ok with an empty text`.
   Ollama answers 404 on `/health`, hence `health_path="/"`.

## Stage 07 scenario

A software factory runs 300 agent coding tickets a day, and the same company runs a support
assistant that handles 2,000 chats a day. All inference, the four workloads together, has a budget
of 10,000 USD a month. A month is 30 days.

The three placements:

- `local`: one machine running Ollama or llama.cpp, with no orchestrator (the stage 02 setup);
- `self-hosted vLLM`: vLLM replicas in the company's Kubernetes cluster in an EU region, one H100
  each (stages 03 and 04);
- `API`: claude-opus-5-5 through the Agent SDK, at 4 USD per million input tokens and 20 USD per
  million output tokens.

The facts:

- Data: support chats, the help-centre index and customer tickets are customer data and must stay
  in the EU. The company's API contract has no EU processing commitment, so no customer data may
  go to the API. Agent coding tickets hold source code and specs, no customer data, and the
  factory's eval sets hold none either.
- Agent coding tickets: a ticket costs 0.60 USD on average on claude-opus-5-5, by the factory's
  cost ledger. On the factory's eval suite, the open models that fit on one GPU solved clearly
  fewer tickets than claude-opus-5-5.
- Support chat: a chat has 6 turns on average; a turn sends 3,000 input tokens (system prompt,
  retrieved passages, history) and returns 200 output tokens. Chats arrive between 08:00 and
  20:00, and the busiest hour carries twice the average hourly load. A self-hosted replica (a 27B
  open model in FP8 on one H100) sustains 400 output tokens per second at the concurrency the
  assistant needs, prompt processing included, and costs 2.50 USD an hour, busy or idle.
- Embeddings and retrieval: the index holds 40,000 help-centre articles and resolved tickets of
  about 800 tokens each; about 2,000 of them change each day and are embedded again, and every chat
  turn embeds its query, about 50 tokens. An open embedding model under 1B parameters meets the
  retrieval target.
- Judge and evals: an LLM judge grades every finished agent ticket against its acceptance
  criteria, as in M2. Its agreement with human labels was measured with claude-opus-5-5 as the
  judge, and a judge call costs 0.03 USD on average.

## Running against a real model

Stage 02 uses Ollama (`ollama pull qwen3.5:0.8b`, then `ollama serve`); Ollama's endpoint is
`http://localhost:11434/v1` and it ignores the API key a client sends. llama.cpp is an alternative
the course did not run: `brew install llama.cpp`, then
`llama-server -hf <repo>:Q4_K_M --port 9931`, and point the load generator at
`http://localhost:9931/v1`. Its `/health` answers 503 while the model loads, so wait for 200 first.
