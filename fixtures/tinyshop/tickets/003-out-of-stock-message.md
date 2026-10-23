# 003: Out-of-stock error says "unknown sku"

**Symptom.** Reserving 6 apples when 5 are in stock raises `ValueError("unknown sku: apple")`.
Support reads that as a catalogue problem. The message must be exactly `out of stock: apple`
(with the requested sku). A sku that is not in stock at all keeps raising `KeyError("unknown sku: ...")`.

**Failing test.** `tests/test_inventory.py::test_reserve_out_of_stock_message`

**Acceptance.** From the repository root,
`pytest --runxfail tests/test_inventory.py::test_reserve_out_of_stock_message -q`
passes, the rest of the suite still passes, and no test file is edited.
