# Audit checklist

`audit.checklist(log_path, head=None)` evaluates these ten items against an audit log. Each item
names the field or event that satisfies it and the EU AI Act provision it derives from. A coding
agent in a software factory is not a high-risk system under Annex III as written, so this is good
practice modelled on the high-risk logging duty, not a legal obligation.

| # | Item | Satisfied by | Derived from |
| --- | --- | --- | --- |
| 1 | `run-start-end`: every run has a start and an end | one `run.start` and one later `run.end` per `run_id` | Art. 12(1) automatic recording of events over the lifetime of the system |
| 2 | `denied-has-reason`: every denied tool call says why | `payload.reason` on every `tool.denied` | Art. 12(2)(a) identifying situations that may present a risk |
| 3 | `taint-resolved`: every taint is cleared by an approval or ends with the run | `taint.set` followed by `approval` and `taint.cleared`, or by `run.end` | Art. 14 human oversight; Art. 12(2)(a) |
| 4 | `no-secrets`: no secret patterns in payloads | `secrets.scrub` finds nothing in any `payload`; redactions logged as `secret.redacted` | Art. 15(5) cybersecurity |
| 5 | `chain-verifies`: the hash chain is intact | `prev_sha256` and `sha256` recomputed by `audit.verify` | Art. 12(1) logging capability; Art. 15(5) integrity |
| 6 | `timestamps-monotonic`: events are ordered in time | `ts` is UTC ISO 8601 and never decreases | Art. 12(2) traceability |
| 7 | `actor-present`: every event says who acted | `actor` in `model`, `host`, `human`; `event` in the allowed names | Art. 12(2)(c) monitoring by deployers, Art. 26(5) |
| 8 | `ticket-id-present`: every event belongs to a run and a ticket | `run_id` and `ticket_id` on every line | Art. 12(2)(b) post-market monitoring, Art. 72 |
| 9 | `tool-use-id`: tool events point at the call | `tool_use_id` on every `tool.call` and `tool.denied` | Art. 12(2) traceability |
| 10 | `append-only`: the log was not truncated | the last `sha256` equals the head the host recorded, else the log ends with `run.end` at a line boundary | Art. 12(1); Art. 19 keeping automatically generated logs |
