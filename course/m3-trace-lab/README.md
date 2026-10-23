# Trace lab

You instrument the M1 ticket harness: OpenTelemetry spans with GenAI attributes for every model call and tool call, cost per task computed from those spans, a budget guard that stops a run, OTLP export to a local Langfuse, a model router with fallback and per-route stats, a query for the costliest tasks, a written cost review, and one live traced ticket.

The GenAI semantic conventions are at status Development. The attribute names below are the constants in `opentelemetry.semconv._incubating.attributes.gen_ai_attributes` from `opentelemetry-semantic-conventions` 0.66b1, which `opentelemetry-sdk` 1.45.1 installs. Use the constants rather than string literals where you can.

## How to run

Run every command below in a terminal at the root of your clone of this repository, after a one-time `uv sync` there; `uv run miubais doctor` lists what this machine has.

```
uv run miubais start m3-trace-lab
```

This copies `course/m3-trace-lab/starter/` to `workspace/m3-trace-lab/` at the repo root. That copy is yours: the stubs under `workspace/m3-trace-lab/src/trace_lab/` raise `NotImplementedError` until you fill them in, and the judgment stage asks for a file in the workspace root, named in its description below. The tests stay in `course/m3-trace-lab/tests/` and import your package from the workspace. `start --force` replaces the workspace with a fresh copy.

```
uv run miubais check m3-trace-lab
```

Runs the stages in order and stops at the first failure, printing its pytest output, so stage 02 waits for stage 01. `--stage <stage id>` runs one stage and `--all` keeps going past a failure. A stage whose `requires` (in `stages.yaml`) are missing on your machine is skipped, not failed. Results are kept in `~/.miubais/progress.json`; `uv run miubais reset m3-trace-lab` forgets them (`--all` for every exercise), and `start --force` does the same along with the fresh copy.

```
uv run miubais hint m3-trace-lab
```

Takes the last stage `check` saw fail, its test output and your diff against the starter, and asks the tutor on your Claude Code login for a nudge of under 90 words that is checked not to hand you the solution. If the model cannot be reached, you get a pointer to the failing test instead.

The **Run check** and **Hint** buttons on the site's exercise page do the same while `uv run miubais serve` is running, and share the progress file with the terminal.

## Stages

1. `01-spans-from-messages`: `spans.record_run(timed, *, ticket_id, tracer_provider, agent_name="ticket-runner", attributes=None, epoch_ns=None) -> RunTrace(trace_id, ticket_id, spans)` turns one recorded message stream (`list[Timed]` from `harnesskit.testing.load_run`) into spans; `spans.provider_for_tests()` returns a `TracerProvider` wired to an `InMemorySpanExporter` through a `SimpleSpanProcessor`, and the exporter. The tests enforce:
   - **Spans.** One root `invoke_agent {agent_name}`; one `chat {model}` span of kind `CLIENT` per assistant turn; one `execute_tool {tool name}` span of kind `INTERNAL` per `tool_use` block. Every other span is a child of the root, in the root's trace. A turn is one `message_id`: parallel tool calls arrive as several `AssistantMessage`s sharing one id with identical `usage`, and they make one `chat` span whose tool calls all belong to that turn.
   - **Timings.** Each `Timed.at_ms` maps to a span time in nanoseconds: `epoch_ns + at_ms * 1_000_000`. `epoch_ns` defaults to the wall clock when `record_run` is called (`time.time_ns()`), so a live run lands at the time it happened and shows up in Langfuse's default date range; the tests pass a fixed `epoch_ns` for the recorded runs and check that it is used exactly. The root starts at `t_ms` 0 and ends at the last `t_ms`. A `chat` span starts at the `t_ms` of the message before it (the root start for the first one) and ends at its own `t_ms`. A tool span opens at its assistant message's `t_ms` and closes at the `t_ms` of the matching `tool_result`.
   - **Root attributes.** `gen_ai.operation.name = "invoke_agent"`, `gen_ai.agent.name`, `gen_ai.conversation.id` (the meta line's `session_id`, left out when there is none), `trace_lab.ticket_id`, the four `gen_ai.usage.*` totals over all turns, `trace_lab.cost_usd` from the result's `total_cost_usd` when the run has a result, and `error.type = <subtype>` (with status `ERROR`) when the result's subtype starts with `error_`.
   - **Chat attributes.** `gen_ai.operation.name = "chat"`, `gen_ai.provider.name = "anthropic"`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.response.id` (the `message_id`), `gen_ai.response.finish_reasons = [stop_reason]`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`, and `gen_ai.usage.input_tokens` by the Anthropic rule: `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. The API's `input_tokens` counts only the uncached tail of the prompt, so copying it under-reports the prompt.
   - **Tool attributes.** `gen_ai.operation.name = "execute_tool"`, `gen_ai.tool.name`, `gen_ai.tool.call.id`; `error.type = "tool_error"` (status `ERROR`) when the result has `is_error`.
   - **No leaked spans.** A tool call whose result never arrives (the run was cut off) is still closed at the last `t_ms`, with `error.type = "no_result"`. Every span `record_run` starts is ended, so the exporter sees all of them.
2. `02-cost-from-spans`: `cost.Prices.load(path=None)` reads a price table (USD per million tokens; the default is the packaged `trace_lab/prices.json`); `cost.span_cost(span, prices)`, `cost.per_task(traces, prices) -> dict[str, TaskCost]` keyed by ticket id, and `cost.reconcile(trace, prices) -> Reconciliation(from_spans, reported, delta)`. The tests enforce:
   - **Formula.** A `chat` span costs `(input * input_price + output * output_price + cache_read * cache_read_price + cache_creation * cache_write_5m_price) / 1e6`, priced by its `gen_ai.request.model`, where `input` is the uncached part: `gen_ai.usage.input_tokens` minus the two cache attributes. Cache reads and cache writes have their own prices; pricing either as plain input moves a cached run's cost by more than 1% and does not move a run that uses no cache. Every other span costs 0.0.
   - **Dedupe.** Each turn is priced once. Stage 01 already makes one `chat` span per `message_id`, so summing `chat` spans counts parallel tool calls once.
   - **Per task.** `TaskCost` sums every run of a ticket: `usd`, `calls` (`chat` spans), `tool_calls` (`execute_tool` spans), `input_tokens` (uncached), `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, and `cache_hit_ratio = cache_read / (input + cache_read + cache_write)`, 0.0 when that denominator is 0. The ratio matches the answer key to 1e-6 for all ten tickets.
   - **Reconcile.** `from_spans` is the sum over the trace's `chat` spans; `reported` is the root's `trace_lab.cost_usd` (`None` when the run has no result); `delta = from_spans - reported` (`None` without a result). On every recorded run with a result `|delta| < 1e-9`.
3. `03-budget-guard`: `budget.BudgetGuard(limit_usd, prices)` is an observer for `harnesskit.runner.run_ticket(..., observer=guard)`; `budget.run_with_budget(ticket_path, repo, *, limit_usd, prices, **run_ticket_kwargs) -> RunReport` passes a fresh guard as the `observer` and the limit as `max_budget_usd` unless the caller sets one, so the SDK's own budget cap is the backstop. The tests enforce:
   - **Estimate.** The guard is called with every message and counts it in `messages_seen`. For each `AssistantMessage` with a `usage` whose `message_id` it has not counted yet, it adds that usage's cost by the stage 02 formula (the API's `input_tokens` there is already the uncached part) to `cost_usd`. Repeated ids from parallel tool calls add nothing.
   - **Trip.** `tripped` becomes `True`, and the call returns `True`, on the first message that takes `cost_usd` strictly above `limit_usd`; an estimate equal to the limit does not trip. The runner stops at that message: no later message is consumed, the report has `stopped_by="budget"`, the note `stopped by observer`, and `cost_usd == guard.cost_usd`. A run that stays under the limit ends `success` with the SDK's `total_cost_usd`.
   - **Floor.** On a live stream the per-step `output_tokens` is a placeholder (the count at `message_start`), so the running estimate is a floor of the real spend; the recorded runs carry real per-message counts.
   - **Unpriced.** A message whose four token counts are all zero adds nothing and is never looked up, so Claude Code's zero-usage `<synthetic>` messages on API failures pass; a message with usage from a model missing in the price table raises a `KeyError` that names the model.
4. `04-otlp-export`: `export.langfuse_headers(public_key, secret_key)`, `export.langfuse_exporter(base_url, public_key, secret_key, *, timeout=5.0) -> OTLPSpanExporter`, `export.provider(exporter, *, batch=True) -> TracerProvider` and `export.export_runs(runs_dir, *, base_url, public_key, secret_key, prices, timeout=5.0) -> ExportSummary(traces, spans, failed, failed_spans)`; `python -m trace_lab.export <runs_dir> --base-url http://localhost:3000 --public-key pk --secret-key sk` prints `traces=… spans=… failed_batches=… lost_spans=…`. The tests run against a fake collector (`tests/fake_collector.py`) and enforce:
   - **Headers.** Exactly `Authorization: Basic <base64 of public_key:secret_key>` and `x-langfuse-ingestion-version: 4`, on every request, sent as OTLP protobuf over HTTP (`Content-Type: application/x-protobuf`). Langfuse takes no gRPC.
   - **Endpoint.** `{base_url}/api/public/otel/v1/traces`, with or without a trailing slash on `base_url`.
   - **Delivery.** `export_runs` records every run under the directory with the stage 01 `record_run` and flushes before returning: the collector receives all 40 traces and every span, with the span names (`invoke_agent ticket-runner`, `chat {model}`, `execute_tool {name}`) and the `gen_ai.*` attributes intact once decoded from the wire. Each `chat` span also carries `gen_ai.usage.cost`, its stage 02 cost, which Langfuse reads as the observation's cost.
   - **Collector down.** A collector that answers 503, or a port nobody listens on, makes `export_runs` return with `failed > 0` (failed export batches), `failed_spans` equal to every span that did not reach the collector (spans in failed batches plus spans never sent after the first failure), and the run counts intact, without raising, in under 10 seconds. The exporter retries with backoff until its `timeout`; the processor's `export_timeout_millis` is not used by `opentelemetry-sdk` 1.45.1, so the bound has to come from the exporter's `timeout` and from not sending more batches after the first one fails.
5. `05-model-router`: `router.Route(name, model, max_budget_usd, max_turns)`; `router.Router(routes, *, fallback_on=frozenset({"budget", "max_turns", "error"}), tracer_provider=None)`; `router.run(ticket_path, repo, *, run_fn=harnesskit.runner.run_ticket, **kwargs) -> Routed(report, route, attempts)` with `Attempt(route, stopped_by, cost_usd)`; `router.stats: dict[str, RouteStats(name, attempts, successes, cost_usd, turns)]`; `router.to_markdown()`. Stage 01's `record_run` takes `attributes=None`, extra attributes for the root span. The tests enforce:
   - **Order.** Routes are tried in list order. Each attempt calls `run_fn(ticket_path, repo, model=route.model, max_turns=route.max_turns, max_budget_usd=route.max_budget_usd, **kwargs)`, so the route's model and limits reach `ClaudeAgentOptions`. Routing stops at the first `success`.
   - **Fallback.** Only a stop in `fallback_on` moves to the next route: by default `budget`, `max_turns` and `error`. A `policy` stop ends routing after that one attempt: a denied action stays denied on a more expensive model. `fallback_on` containing `policy` or `success` is a `ValueError`, as are an empty route list and duplicate route names. When every route fails, `Routed.report` is the last report and `route` the last route's name.
   - **Stats.** Every route has a `RouteStats` from the start, zeros until it is tried. Each attempt adds 1 to `attempts`, 1 to `successes` when it ended `success`, its `cost_usd` and its `turns`. Stats accumulate across `run` calls; `to_markdown()` is a table with a header and one row per route (`route`, `model`, `attempts`, `successes`, `cost_usd`, `turns`).
   - **Spans.** With a `tracer_provider`, each attempt's `report.messages` are recorded with `record_run` (message index as `t_ms`), one trace per attempt, the root span carrying `trace_lab.route`.
   - **Why a client-side router.** `ClaudeAgentOptions.fallback_model` switches models when the provider fails (overload, unavailable model); it does not react to a run that hit its budget or its turn limit, which are the stops this router handles. With the real `run_ticket`, a fallback attempt resumes the session the failed attempt stored, so the next model starts from the work already done and the report's cost is that attempt's own spend.
6. `06-top-costly`: `query.top_costly(traces, prices, n=5) -> list[TaskCost]`, `query.to_markdown(rows) -> str` and `python -m trace_lab.query <runs_dir> --top 5 [--prices path]`. The tests enforce:
   - **Ranking.** Rows are stage 02's `per_task` totals sorted by `usd` descending, ties broken by ticket id ascending, cut to `n`. Over the 40 recorded runs the top five match the answer key.
   - **Table.** `to_markdown` gives a header row `ticket | usd | calls | cache-hit %`, a separator row and one row per `TaskCost`; `usd` to four decimals, `calls` the number of `chat` spans, `cache-hit %` the stage 02 `cache_hit_ratio` times 100 to one decimal.
   - **CLI.** The command loads every run under the directory with `load_run`, records it with `record_run` on an in-memory provider and prints the table.
7. `07-cost-review` (judgment stage): run the stage 06 query over the 40 recorded runs, read the runs of the five costliest tickets, and write `COST_REVIEW.md` in your workspace root with a table `| ticket | cause | lever | evidence |`. The tests enforce:
   - **Rows.** Exactly five rows, one per ticket, and the tickets are the five costliest (any order).
   - **Causes.** Each `cause` is one of `no-cache`, `loop`, `big-context`, `retries`, `expensive-model`; at least four of the five agree with the answer key.
   - **Levers.** Each `lever` is the one for its row's cause: `no-cache` → `enable-caching`, `loop` → `cap-turns`, `big-context` → `trim-context`, `retries` → `fix-tool`, `expensive-model` → `downgrade-model`.
   - **Evidence.** Each `evidence` cell cites at least one line of a recorded run as `rNNN:LL` (run id and 1-based line number in `rNNN.jsonl`). Every cited run is a run of that row's ticket (its meta line says so), and the line is a real line after the meta line.
8. `08-live-traced-ticket` (live; needs Docker and a logged-in Claude Code): run tinyshop ticket `001-discount-rounding` on `claude-opus-5-5` through `budget.run_with_budget` (limit 0.75 USD, 12 turns) on a fresh git copy of `fixtures/tinyshop`, record its messages with `record_run` on `export.provider(export.langfuse_exporter("http://localhost:3000", "pk-lf-miubais", "sk-lf-miubais"))`, flush, and read the trace back from the local Langfuse. The test wraps the SDK query to timestamp each message as it arrives, so the budget guard stays the runner's observer and can still stop the run. It skips with `needs Langfuse: docker compose -f course/m3-trace-lab/docker-compose.yml up -d` unless `docker compose ps` shows `langfuse-web` running and healthy. The tests enforce:
   - **Offline.** The exporter for the local stack posts to `http://localhost:3000/api/public/otel/v1/traces` with the Basic auth and `x-langfuse-ingestion-version: 4` headers, and the compose file pins the image tags below with every published port on `127.0.0.1`. These run in every check.
   - **Read back.** Within 60 seconds `GET /api/public/v2/observations?traceId=<trace id>&limit=100` (Basic auth) returns one observation per span (the test reads one page, so the run may have at most 100 spans): exactly one root, `invoke_agent ticket-runner` (type `AGENT`), and every other observation its child, among them at least one `chat` generation (`GENERATION`) and one tool call (`TOOL`, which Langfuse names after the tool). Langfuse v4 runs in events-only mode, where the older `GET /api/public/traces` answers that it is not available.
   - **Record.** The run ends `success` with a positive `cost_usd`. Only then does the test write `runs/live-<UTC date>.json` in your workspace (a run the budget guard stopped, or any other ending, fails the stage and leaves no record); it holds the report's `stopped_by`, `turns`, `cost_usd` and `files_changed`, the OTel trace id, and the span and observation counts. No message bodies.

## Recorded runs

`fixtures/harness-runs/runs/r001.jsonl` to `r040.jsonl` are 40 synthetic runs of the harness on ten tinyshop tickets, four runs each, in the run-file format of `harnesskit.testing.load_run`. `fixtures/harness-runs/README.md` describes the format; `fixtures/harness-runs/prices.json` (and the copy in `trace_lab/prices.json`) is the price table in USD per million tokens. Load a run with:

```python
from harnesskit.testing import load_run

timed = load_run("fixtures/harness-runs/runs/r001.jsonl")
```

## Local Langfuse (stage 08)

Stage 08 needs Docker and a logged-in Claude Code. `docker-compose.yml` is a trimmed copy of Langfuse's own self-hosting compose file for v4: six containers, the Langfuse web app and its worker (`langfuse/langfuse:4`, `langfuse/langfuse-worker:4`), Postgres 17, ClickHouse 25.12, Redis 7 and MinIO (Chainguard publishes only `latest` for it). Langfuse recommends at least 16 GiB of memory for a self-hosted stack; on Docker Desktop give the VM that much, or close other containers if it starts slowly. From the repository root:

```
docker compose -f course/m3-trace-lab/docker-compose.yml up -d
docker compose -f course/m3-trace-lab/docker-compose.yml ps
```

The first start pulls the images and runs the database migrations; `langfuse-web` turns `healthy` when its health endpoint answers, usually within a few minutes. The UI is at `http://localhost:3000`. Only the UI (3000) and MinIO's S3 port (9090, for media uploads from the browser) are published, both on `127.0.0.1`; Postgres, ClickHouse and Redis stay inside the compose network, so they do not clash with a local database on the usual ports.

The stack is created with organisation `miubais`, project `m3-trace-lab` and the API keys `pk-lf-miubais` / `sk-lf-miubais`. Log in as `learner@miubais.local` with the password `miubais-change-me`, or set `LANGFUSE_INIT_USER_PASSWORD` in your shell before the first `up` to choose your own (it is applied only when the user is created). The keys, passwords and secrets in the compose file are fixed local placeholders, not credentials: do not expose this stack beyond your machine.

Stop it with `docker compose -f course/m3-trace-lab/docker-compose.yml down`; add `-v` to delete its volumes (traces, users, keys) as well.
