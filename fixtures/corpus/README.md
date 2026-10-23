# corpus

The fixture corpus for the M4 retrieval lab: 32 documents and a golden set of 48 queries.

## Layout

- `docs/`: 29 Markdown files, a frozen snapshot of the first four lessons of M0, M1, M2, M3, M5
  and M7 (`<module>-<stem>.md`, `course snapshot 2026-10-17`) and the interview-angle pages of M0,
  M1, M2, M3 and M5 (`<module>-07-interview-angle.md`, `course snapshot 2026-10-23`). YAML
  frontmatter is stripped; a lesson whose body has no H1 gets `# <title>` from its frontmatter.
- `stories/`: three public-domain Project Gutenberg texts as plain text, story body only (see
  `LICENSES.md`). Each starts with the title and a `by <author>` line; for the Poe extract both
  lines were written to match the other two, since the volume prints only an upper-case heading.
- `golden.yaml`: the golden set.
- `MANIFEST.md`: every file with its source path and provenance, written by `build_snapshot.py`.

`doc_id` is the file stem: `m0-01-tokens-prefill-decode`, `m1-07-interview-angle`,
`gift-of-the-magi`.

## Rebuilding the snapshot

```
python fixtures/corpus/build_snapshot.py [--root <repo>] [--out <dir>]
```

Stdlib only, deterministic and idempotent: it clears `docs/*.md`, copies the 29 sources and
rewrites `MANIFEST.md`. Re-running it after the lessons change produces a new snapshot, which
invalidates golden anchors that no longer occur; `tools/miubais/tests/test_corpus.py` catches
that.

`MIUBAIS_REFRESH_CORPUS=1 uv run --frozen pytest tools/miubais/tests/test_corpus.py -k reproducible`
checks that the committed snapshot equals a fresh build. It is skipped by default because the
live lessons keep changing after the snapshot date. A refresh changes the chunks, so re-measure
and re-pin `test_05` (`PINNED`, `RECALL_AT_50`, `FAILED`), `test_06` `SUPPORTED_GOLDEN`, `test_03`
`LEXICAL_TEXT_ONLY`, `tests/KEY.yaml`, `reference/RETRIEVAL_ANALYSIS.md` and the numbers quoted in
the M4 lessons and READMEs.

The stories are not rebuilt by the script: they were extracted once by hand from the
Gutenberg files (text between the `*** START OF` and `*** END OF` markers, trailing spaces
trimmed, runs of blank lines collapsed; for #2148 the lines from `THE TELL-TALE HEART.` to the
next story, `BERENICE`, dedented).

## golden.yaml

48 hand-written queries: 36 over `docs/` and 12 over `stories/`, 16 of each kind. Each entry is
`{id, query, doc_id, anchor, kind}`.

- `factual`: asks for a specific fact stated in the anchor.
- `conceptual`: paraphrases the idea without sharing content words with the anchor.
- `lexical`: contains an identifier or rare term (a flag, a constant, an error string, an
  unusual word) that appears verbatim in the anchor.

`anchor` is a 6 to 20 word verbatim phrase from one paragraph of the document that occurs
exactly once in it, case-insensitive and whitespace-normalised. A retrieved chunk is relevant to
a query when its text contains the anchor under the same normalisation, so relevance does not
depend on chunking parameters.
