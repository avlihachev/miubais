# go-ts-mini

A translation jobs service: Go HTTP API (standard library only) with an in-memory store, a proto
contract, numbered SQL migrations, a JSON changelog and a TypeScript web client.

- `go test ./...` runs the Go tests; `node --test` (Node 26, from the repository root) runs the
  `web/src/*.test.ts` files with built-in type stripping.
- `internal/jobs` holds the model and the service, `internal/store` the in-memory
  repository, `internal/api` the HTTP handlers and the error helper.
- `proto/` is the published contract; `migrations/` are applied in number order and never
  rewritten; `CHANGELOG.json` lists user-visible changes, newest version first.
- Review rules live in `.claude/rules/`; each rule names the paths it covers.
