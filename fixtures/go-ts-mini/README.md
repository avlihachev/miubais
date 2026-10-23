# go-ts-mini

A small translation jobs service used as the target repository for the M7 capstone: an agent reviews
twelve pull requests against it before a human does and says what blocks each one from prod.
It is original work under the MIT license (see `LICENSE`).

## The repository

| Path | What it holds |
| --- | --- |
| `cmd/server` | `main`: serves the API on `$ADDR` (default `:8080`) |
| `internal/jobs` | `Job`, `Status`, `ParseStatus`, `Service` (`Create`, `Get`, `List`, `Cancel`) |
| `internal/store` | `Memory`, the in-memory repository |
| `internal/api` | HTTP handlers with input validation; `writeError` gives every error the same shape |
| `proto/jobs/v1` | the published contract (text only, nothing generates code from it) |
| `migrations` | `0001`–`0004`, applied in number order |
| `CHANGELOG.json` | user-visible changes, newest version first |
| `web/src` | TypeScript client: `api.ts`, `format.ts`, `status.ts` and their tests |
| `.claude/` | `CLAUDE.md` and five review rules, four of them scoped with `paths:` |

The HTTP API: `GET /jobs[?status=]`, `POST /jobs`, `GET /jobs/{id}`,
`POST /jobs/{id}/cancel`. Errors are `{"error": {"code": "...", "message": "..."}}`.

Go uses the standard library only (`go.mod` says `go 1.27`). The web tests run on Node 26 with
built-in type stripping, so there is no build step and no `node_modules`; `web/tsconfig.json`
is there for editors.

```bash
cd fixtures/go-ts-mini
go test ./...   # 3 packages
node --test     # finds web/src/*.test.ts
```

Run `node --test` from the fixture root: `node --test web/` treats `web/` as a file name and
fails on Node 26.

## The pull requests

`prs/pr-01 … pr-12` each hold `patch.diff` (a unified diff with `a/` and `b/` prefixes, applied
with `git apply` from the fixture root) and `meta.json` with `title`, `author`, `created_at`,
`approvals` and `description`. `MANIFEST.md` lists them. Some are clean and some are not; what
is wrong with each one is the exercise, so the answers live in the exercise's `tests/` folder,
not here.

```bash
cp -R fixtures/go-ts-mini /tmp/review && cd /tmp/review
git apply --check prs/pr-01/patch.diff && git apply prs/pr-01/patch.diff
go test ./... && node --test
```

The rules in `.claude/rules/` are what a reviewer cites: field numbers in `proto/` and applied
migrations are never reused or rewritten, `proto/` and `migrations/` changes need two approvals,
handlers validate input and never swallow errors, the web client has no `any`, and every
user-visible change gets a changelog entry.
