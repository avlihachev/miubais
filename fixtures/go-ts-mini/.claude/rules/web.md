---
paths: "web/**/*.{ts,tsx}"
---

# Web client

- No `any`: use precise types or `unknown` with a check.
- Every exported helper in `format.ts` keeps its tests in `format.test.ts`; never delete a test
  to make a change pass.
- Credentials never live in source: the client receives them at runtime.
