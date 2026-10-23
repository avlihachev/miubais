---
paths:
  - "proto/**/*.proto"
---

# Proto contract

- Never reuse a field number. Numbers that were ever published belong to their old meaning
  forever, even after the field is gone, because old clients still send them.
- When a field is removed, add its number and its name to a `reserved` statement in the same
  message, for example `reserved 4;` and `reserved "customer_email";`.
- Never delete or edit an existing `reserved` statement.
- A change under `proto/` needs two approvals before merge.
