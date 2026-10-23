---
paths:
  - "internal/api/**/*.go"
  - "internal/jobs/**/*.go"
---

# HTTP API

- Validate every request field before it reaches the service: required fields, ranges and
  lengths. Invalid input answers 400 through `writeError` with code `invalid_input`.
- Every error response goes through `writeError` or `writeServiceError`, so the body is always
  `{"error": {"code": "...", "message": "..."}}`.
- Never swallow an error: no `_ =` on a call that returns an error, no `if err != nil` branch
  that carries on as if it succeeded.
- Renaming or removing a JSON field is a breaking change: it needs a `CHANGELOG.json` entry and
  a major version bump.
