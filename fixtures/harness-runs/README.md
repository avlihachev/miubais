# harness-runs

40 recorded runs of the M1 ticket harness for the M3 trace lab, on ten tinyshop tickets (four
runs each). They are synthetic: `generate.py` (stdlib only, seeded) writes them, and
`MANIFEST.md` lists every file with its provenance, ticket, model and ending. No model was called.

## Format

`runs/r001.jsonl … r040.jsonl` use the run-file format of `harnesskit.testing.load_run` (see
`fixtures/harnesskit/README.md`): a `meta` line with `ticket_id` and `session_id` at `t_ms` 0,
then `assistant`, `user` (tool results) and `result` lines, each with `t_ms` in milliseconds
since the run started. `load_run(path)` turns a file back into `Timed(at_ms, message)` items
holding Agent SDK message objects.

- Every assistant line carries `message_id`, `model`, `stop_reason` and `usage` with
  `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`.
- Parallel tool calls in one turn appear as several assistant lines that share one `message_id`
  and carry identical `usage`, one `tool_use` block each, as the Agent SDK delivers them. Count
  a turn once per `message_id`; adding every line counts its tokens several times.
- Per-message `output_tokens` here are the real counts for that message. Live streams do not
  carry them: there the per-step `output_tokens` is a placeholder (the count at
  `message_start`) and the real output total is only on the result's `usage` and
  `model_usage`.
- Each tool result arrives 50–900 ms after the assistant line that asked for it.
- `total_cost_usd` and `model_usage[model].costUSD` follow `prices.json` (a copy of the M0
  table) with `(input*input_price + output*output_price + cache_read*cache_read_price +
  cache_creation*cache_write_5m_price) / 1e6`, over token totals summed per unique
  `message_id`. Every run uses one model.
- Two runs are truncated: `r014` and `r039` end on an assistant `tool_use` with no tool result
  and no `result` line. One run ends with `subtype: error_max_turns`. Every other run ends with
  `success`.

The runs differ in what drives their cost: whether the prompt cache is used, how many turns
they take, how large the context gets, how many tool calls fail and are retried, and which model
runs them. Finding out which ticket spends its money on what is the exercise, so this file does
not say.

## Regenerating

```bash
uv run python fixtures/harness-runs/generate.py
```

It rewrites `runs/`, `prices.json`, `MANIFEST.md` and the answer key
`course/m3-trace-lab/tests/KEY.yaml`. `tools/miubais/tests/test_harness_runs.py` checks that
regeneration is byte-identical and that the runs keep the properties above.
