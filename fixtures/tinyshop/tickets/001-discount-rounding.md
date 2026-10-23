# 001: Discounted totals round half-cents down

**Symptom.** A cart worth 12.25 with code `SAVE10` comes out at 11.02. Finance expects 11.03: half a
cent always rounds up. The same happens with `HALF` on 0.25 (0.12 instead of 0.13).

**Failing test.** `tests/test_pricing.py::test_discount_rounds_half_up`

**Acceptance.** From the repository root,
`pytest --runxfail tests/test_pricing.py::test_discount_rounds_half_up -q`
passes, the rest of the suite still passes, and no test file is edited.
