---
paths:
  - "migrations/*.sql"
---

# SQL migrations

- Files are named `NNNN_description.sql`; a new migration takes the next number, which is the
  highest existing number plus one. Two files must never share a number.
- Never edit a migration that is already in the repository: it has been applied somewhere.
  Fix it with a new migration instead.
- A change under `migrations/` needs two approvals before merge.
